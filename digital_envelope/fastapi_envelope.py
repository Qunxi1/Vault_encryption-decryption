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

def delete_key(key_name: str):
    # 将密钥设置为可删除的状态
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/keys/{key_name}/config"
    r = requests.post(url, headers=HEADERS, json={"deletion_allowed": True})
    if r.status_code != 200:
        raise RuntimeError(f"deletion_allowed set failed: {r.text}")

    # 删除密钥
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/keys/{key_name}"
    r = requests.delete(url, headers=HEADERS)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"delete_key failed: {r.text}")

def datakey_plain(sym_key_name: str):
    """返回 (plaintext_DEK_bytes, ciphertext_DEK_str)"""
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/datakey/plaintext/{sym_key_name}"
    r = requests.post(url, headers=HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"datakey_plain failed: {r.text}")
    data = r.json()["data"]
    # Vault 返回的 plaintext 是 base64 编码过的，要解码成真正的 bytes 密钥
    return base64.b64decode(data["plaintext"]), data["ciphertext"]

def encrypt_with_rsa(asym_key_name: str, plaintext_bytes: bytes) -> str:
    b64 = base64.b64encode(plaintext_bytes).decode()
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/encrypt/{asym_key_name}"
    r = requests.post(url, headers=HEADERS, json={"plaintext": b64})
    if r.status_code != 200:
        raise RuntimeError(f"RSA encrypt failed: {r.text}")
    return r.json()["data"]["ciphertext"]

def get_public_key(asym_key_name: str) -> str:
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/keys/{asym_key_name}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"get_public_key failed: {r.text}")
    # 对 RSA，public_key 在 keys->version->public_key
    keys = r.json()["data"]["keys"]
    # 提取最新版本的公钥
    latest_version = max(keys.keys(), key=int)
    return keys[latest_version]["public_key"]

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
@app.post("/envelope/encrypt")
'''示例
# 加密生成数字信封
curl -X POST http://localhost:5000/envelope/encrypt \
  -F "file=@bigfile.tar.gz" \
  -F "sym_key_name=my-sym-key" \
  -F "asym_key_name=my-rsa-key" \
  --output digital_envelope.zip
'''
async def encrypt_envelope(
    file: UploadFile = File(...),
    sym_key_name: str = Form(...),
    asym_key_name: str = Form(...)
):
    try:
        # 1. 对称根密钥
        create_key(sym_key_name)

        # 2. 派生 DEK
        plaintext_dek, _ = datakey_plain(sym_key_name)

        # 3. 大文件加密
        # 因fastapi是异步框架，而大文件读取可能会花费很多时间，为不阻塞整个线程，加await
        raw = await file.read()
        cipher_file = encrypt_large_file(plaintext_dek, raw)

        # 4. 非对称密钥
        create_key(asym_key_name, key_type="rsa-2048")
        rsa_cipher_dek = encrypt_with_rsa(asym_key_name, plaintext_dek)
        public_key_pem = get_public_key(asym_key_name)

        # 5. 销毁对称根密钥
        delete_key(sym_key_name)

        # 6. 打包数字信封
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("data.bin", cipher_file)
            z.writestr("encrypted_key.txt", rsa_cipher_dek)
            z.writestr("public_key.pem", public_key_pem)
            z.writestr("asym_key_name.txt", asym_key_name)
        buf.seek(0)

        headers = {"Content-Disposition": "attachment; filename=digital_envelope.zip"}
        return StreamingResponse(buf, media_type="application/zip", headers=headers)

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")

@app.post("/envelope/decrypt")
'''示例
curl -X POST http://localhost:5000/envelope/decrypt \
  -F "encrypted_key=@encrypted_key.txt" \
  -F "asym_key_name=my-rsa-key" \
  -F "encrypted_file=@data.bin" \
  --output recovered_file.bin
'''
async def decrypt_envelope(
    encrypted_key: UploadFile = File(...),        # 加密后的DEK
    asym_key_name: str = Form(...),              # RSA密钥名
    encrypted_file: UploadFile = File(...),      # data.bin
):
    try:
        # 1. 获取加密后的对称密钥
        encrypted_dek = (await encrypted_key.read()).decode()

        # 2. 用 Vault 的 RSA 私钥解密出明文 DEK
        url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/decrypt/{asym_key_name}"
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

        # 5. 销毁明文/密文 DEK（从内存清除；Vault中已无存储）
        del plaintext_dek, plaintext_dek_b64, encrypted_dek, ciphertext

        # 6. 返回解密后的大文件
        return StreamingResponse(io.BytesIO(decrypted_data),
                                 media_type="application/octet-stream",
                                 headers={"Content-Disposition": "attachment; filename=decrypted_data.bin"})

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
