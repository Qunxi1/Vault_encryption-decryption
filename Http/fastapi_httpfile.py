from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
import requests
import base64
import io
from config import VAULT_ADDR, VAULT_TOKEN

'''
启动服务
uvicorn httpfile:app --host 0.0.0.0 --port 5000
'''

app = FastAPI()

VAULT_TRANSIT_PATH = "transit"

# ----------------- 工具函数 -----------------

# 创建密钥
def create_key(key_name: str):
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/keys/{key_name}"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    response = requests.post(url, headers=headers)
    if response.status_code not in [200, 204]:
        if "already exists" not in response.text:
            raise Exception(f"Key creation failed: {response.text}")

# 加密数据
def encrypt_data(key_name: str, plaintext_bytes: bytes) -> bytes:
    b64_plaintext = base64.b64encode(plaintext_bytes).decode()
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/encrypt/{key_name}"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    json_data = {"plaintext": b64_plaintext}
    response = requests.post(url, headers=headers, json=json_data)
    if response.status_code != 200:
        raise Exception(f"Encryption failed: {response.text}")
    ciphertext = response.json()["data"]["ciphertext"]
    return ciphertext.encode()

# 解密数据
def decrypt_data(key_name: str, ciphertext: str) -> bytes:
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/decrypt/{key_name}"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    json_data = {"ciphertext": ciphertext}
    response = requests.post(url, headers=headers, json=json_data)
    if response.status_code != 200:
        raise Exception(f"Decryption failed: {response.text}")
    plaintext_b64 = response.json()["data"]["plaintext"]
    return base64.b64decode(plaintext_b64)

# ----------------- API 路由 -----------------

@app.post("/encrypt")
'''
请求样例
curl -X POST http://localhost:5000/encrypt \
  -F "file=@test.txt" \
  -F "key_name=my-encryption-key" \
  --output encrypted.txt

'''
async def encrypt_file(file: UploadFile = File(...), key_name: str = Form(...)):
    try:
        content = await file.read()
        create_key(key_name)
        ciphertext = encrypt_data(key_name, content)
        return StreamingResponse(io.BytesIO(ciphertext),
                                 media_type="application/octet-stream",
                                 headers={"Content-Disposition": "attachment; filename=encrypted.txt"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/decrypt")
'''
请求样例
curl -X POST http://localhost:5000/decrypt \
  -F "file=@encrypted.txt" \
  -F "key_name=my-encryption-key" \
  --output decrypted.txt

'''
async def decrypt_file(file: UploadFile = File(...), key_name: str = Form(...)):
    try:
        ciphertext = (await file.read()).decode()
        plaintext = decrypt_data(key_name, ciphertext)
        return StreamingResponse(io.BytesIO(plaintext),
                                 media_type="application/octet-stream",
                                 headers={"Content-Disposition": "attachment; filename=decrypted.txt"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
