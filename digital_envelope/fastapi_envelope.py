from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import requests, base64, io, os, zipfile, secrets, json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from config import VAULT_ADDR, VAULT_TOKEN
import subprocess
import tempfile
# 调试包
import traceback

app = FastAPI()
VAULT_TRANSIT_PATH = "transit"
HEADERS = {"X-Vault-Token": VAULT_TOKEN}

# ---------- Vault 工具函数 ----------
def create_key(key_name: str, key_type="aes256-gcm96", exportable=False):
    """创建 Transit 密钥（存在则忽略）"""
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/keys/{key_name}"
    payload = {"type": key_type, "exportable": exportable}
    r = requests.post(url, headers=HEADERS, json=payload)
    if r.status_code not in (200, 204) and "already exists" not in r.text:
        raise RuntimeError(f"create_key failed: {r.text}")

def datakey_plain(sym_key_name: str):
    """返回 (plaintext_DEK_bytes, ciphertext_DEK_str)"""
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/datakey/plaintext/{sym_key_name}"
    r = requests.post(url, headers=HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"datakey_plain failed: {r.text}")
    data = r.json()["data"]
    # Vault 返回的 plaintext 是 base64 编码过的，要解码成真正的 bytes 密钥
    return base64.b64decode(data["plaintext"]), data["ciphertext"]

# ---------- Luks加密 ----------
def encrypt_large_file(dek: bytes, plaintext: bytes):
    """
    使用 LUKS 加密大文件，返回密文和独立的 header
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        plain_path = os.path.join(tmpdir, "plain_data.bin")
        luks_data_path = os.path.join(tmpdir, "luks_data.img")
        luks_header_path = os.path.join(tmpdir, "luks_header.bin")

        # 保存明文文件
        with open(plain_path, "wb") as f:
            f.write(plaintext)

        # 创建与明文等长的密文容器，+手动补齐512字节对齐
        remainder = len(plaintext) % 512
        if remainder != 0:
            padding = 512 - remainder
        else:
            padding = 0

        # 创建与明文等长的密文容器
        with open(luks_data_path, "wb") as f:
            f.write(b"\x00" * (len(plaintext) + padding))

        # 创建loop设备
        losetup = subprocess.run(["losetup", "--find", "--show", luks_data_path],
                                 stdout=subprocess.PIPE, check=True, text=True)
        loop_device = losetup.stdout.strip()

        try:
            # luksFormat
            subprocess.run([
                "cryptsetup", "luksFormat",
                "--type", "luks2",
                "--header", luks_header_path,
                "--batch-mode",
                loop_device,
                "--key-file", "-"
            ], input=dek, check=True)

            # 打开 luks 快设备
            subprocess.run([
                "cryptsetup", "open",
                "--header", luks_header_path,
                loop_device, "luks_tmp",
                "--key-file", "-"
            ], input=dek, check=True)

            # 写入明文
            subprocess.run(["dd", f"if={plain_path}", "of=/dev/mapper/luks_tmp", "bs=1M", "status=none"], check=True)

            subprocess.run(["cryptsetup", "close", "luks_tmp"], check=True)

            with open(luks_data_path, "rb") as f:
                encrypted_data = f.read()
            with open(luks_header_path, "rb") as f:
                header_data = f.read()

            return encrypted_data, header_data

        finally:
            subprocess.run(["losetup", "-d", loop_device], check=False)

# ---------- API ----------
'''示例
# 加密生成数字信封
curl -X POST http://localhost:5000/envelope/encrypt \
  -F "file=@bigfile.tar.gz" \
  -F "sym_key_name=my-sym-key" \
  --output digital_envelope.zip
'''
@app.post("/envelope/encrypt")
async def encrypt_envelope(
    file: UploadFile = File(...),
    sym_key_name: str = Form(...)
):
    try:
        # 1. 对称根密钥
        create_key(sym_key_name)

        # 2. 派生 DEK
        plaintext_dek, ciphertext_dek = datakey_plain(sym_key_name)

        # 3. 大文件加密
        # 因fastapi是异步框架，而大文件读取可能会花费很多时间，为不阻塞整个线程，加await
        raw = await file.read()
        cipher_file, header_data = encrypt_large_file(plaintext_dek, raw)

        # 4. 打包数字信封
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("data.bin", cipher_file)
            z.writestr("luks_header.bin", header_data)
            z.writestr("encrypted_key.txt", ciphertext_dek)
            z.writestr("key_name.txt", sym_key_name)
        buf.seek(0)

        headers = {"Content-Disposition": "attachment; filename=digital_envelope.zip"}
        return StreamingResponse(buf, media_type="application/zip", headers=headers)

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")

'''示例
curl -X POST http://localhost:5000/envelope/decrypt \
  -F "encrypted_key=@encrypted_key.txt" \
  -F "key_name=my-sym-key" \
  -F "encrypted_file=@data.bin" \
  -F "luks_header=@luks_header.bin" \
  --output recovered_file.bin
'''
@app.post("/envelope/decrypt")
async def decrypt_envelope(
    encrypted_key: UploadFile = File(...),        # 加密后的DEK
    key_name: str = Form(...),              # 根密钥名
    encrypted_file: UploadFile = File(...),      # data.bin
    luks_header: UploadFile = File(...),         # luks_header.bin
):
    try:
        # 1. 获取加密后的对称密钥
        encrypted_dek = (await encrypted_key.read()).decode()

        # 2. 解密出明文 DEK
        url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/decrypt/{key_name}"
        resp = requests.post(url, headers=HEADERS, json={"ciphertext": encrypted_dek})
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"RSA解密失败: {resp.text}")
        plaintext_dek_b64 = resp.json()["data"]["plaintext"]
        plaintext_dek = base64.b64decode(plaintext_dek_b64)

        # 3. 保存密文（LUKS 容器）到临时文件
        with tempfile.TemporaryDirectory() as tmpdir:
            luks_data_path = os.path.join(tmpdir, "data.img")
            luks_header_path = os.path.join(tmpdir, "header.bin")
            plain_path = os.path.join(tmpdir, "recovered_output.bin")

            with open(luks_data_path, "wb") as f:
                f.write(await encrypted_file.read())
            with open(luks_header_path, "wb") as f:
                f.write(await luks_header.read())

            subprocess.run([
                "cryptsetup", "open",
                "--header", luks_header_path,
                luks_data_path, "luks_tmp",
                "--key-file", "-"
            ], input=plaintext_dek, check=True)

            subprocess.run(["dd", f"if=/dev/mapper/luks_tmp", f"of={plain_path}", "bs=1M"], check=True)

            subprocess.run(["cryptsetup", "close", "luks_tmp"], check=True)

            with open(plain_path, "rb") as f:
                decrypted_data = f.read()

        # 4. 返回解密后的大文件
        return StreamingResponse(io.BytesIO(decrypted_data),
                                 media_type="application/octet-stream",
                                 headers={"Content-Disposition": "attachment; filename=decrypted_data.bin"})

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
