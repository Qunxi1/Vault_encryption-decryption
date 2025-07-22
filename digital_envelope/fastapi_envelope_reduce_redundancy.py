from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import requests, base64, io, os, zipfile, secrets, json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from config import VAULT_ADDR, VAULT_TOKEN
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

# ---------- 本地加密 ----------
def encrypt_large_file(dek: bytes, plaintext: bytes) -> bytes:
    """AES‑GCM；返回 nonce + 密文（含 tag）"""
    aesgcm = AESGCM(dek)
    # 96bit的随机数，每次加密必须用不同的nonce(GCM模式要求)
    nonce = os.urandom(12)  # 96‑bit
    # 返回加密内容和校验信息的密文
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext

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
        cipher_file = encrypt_large_file(plaintext_dek, raw)

        # 4. 打包数字信封
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("data.bin", cipher_file)
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
  -F "key_name=my-rsa-key" \
  -F "encrypted_file=@data.bin" \
  --output recovered_file.bin
'''
@app.post("/envelope/decrypt")
async def decrypt_envelope(
    encrypted_key: UploadFile = File(...),        # 加密后的DEK
    key_name: str = Form(...),              # 密钥名
    encrypted_file: UploadFile = File(...),      # data.bin
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

        # 3. 获取密文文件内容
        enc_file = await encrypted_file.read()
        nonce = enc_file[:12]
        ciphertext = enc_file[12:]

        # 4. 用明文 DEK 解密文件
        aesgcm = AESGCM(plaintext_dek)
        try:
            decrypted_data = aesgcm.decrypt(nonce, ciphertext, None)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AES解密失败: {str(e)}")

        # 5. 返回解密后的大文件
        return StreamingResponse(io.BytesIO(decrypted_data),
                                 media_type="application/octet-stream",
                                 headers={"Content-Disposition": "attachment; filename=decrypted_data.bin"})

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
