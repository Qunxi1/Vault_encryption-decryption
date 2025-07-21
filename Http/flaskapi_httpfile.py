from flask import Flask, request, send_file, jsonify
import requests
import base64
import io
from config import VAULT_ADDR, VAULT_TOKEN

app = Flask(__name__)

VAULT_TRANSIT_PATH = "transit"

# 创建密钥（如果已存在，会忽略）
def create_key(key_name):
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/keys/{key_name}"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    response = requests.post(url, headers=headers)
    if response.status_code not in [200, 204]:
        if "already exists" not in response.text:
            raise Exception(f"Key creation failed: {response.text}")

# 调用 Vault API 加密数据
def encrypt_data(key_name, plaintext_bytes):
    # base64 编码原始数据
    b64_plaintext = base64.b64encode(plaintext_bytes).decode()

    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/encrypt/{key_name}"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    json_data = {
        "plaintext": b64_plaintext
    }

    response = requests.post(url, headers=headers, json=json_data)
    if response.status_code != 200:
        raise Exception(f"Encryption failed: {response.text}")
    
    ciphertext = response.json()["data"]["ciphertext"]
    return ciphertext.encode()  # 转为 bytes

def decrypt_data(key_name, ciphertext):
    url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/decrypt/{key_name}"
    headers = {"X-Vault-Token": VAULT_TOKEN}
    json_data = {
        "ciphertext": ciphertext
    }

    response = requests.post(url, headers=headers, json=json_data)
    if response.status_code != 200:
        raise Exception(f"Decryption failed: {response.text}")
    
    # Vault 返回 base64 明文
    plaintext_b64 = response.json()["data"]["plaintext"]
    return base64.b64decode(plaintext_b64)

@app.route('/encrypt', methods=['POST'])
'''
请求样例
curl -X POST http://localhost:5000/encrypt \
  -F "file=@test.txt" \
  -F "key_name=my-encryption-key" \
  --output encrypted.txt

'''
def encrypt_file():
    if 'file' not in request.files or 'key_name' not in request.form:
        return jsonify({"error": "Missing file or key_name"}), 400

    file = request.files['file']
    key_name = request.form['key_name']

    file_bytes = file.read()

    try:
        create_key(key_name)
        ciphertext_bytes = encrypt_data(key_name, file_bytes)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 将密文作为文件返回
    return send_file(
        io.BytesIO(ciphertext_bytes),
        download_name="encrypted.txt",
        as_attachment=True,
        mimetype='application/octet-stream'
    )

@app.route('/decrypt', methods=['POST'])
'''
请求样例
curl -X POST http://localhost:5000/decrypt \
  -F "file=@encrypted.txt" \
  -F "key_name=my-encryption-key" \
  --output decrypted.txt

'''
def decrypt_file():
    if 'file' not in request.files or 'key_name' not in request.form:
        return jsonify({"error": "Missing file or key_name"}), 400

    file = request.files['file']
    key_name = request.form['key_name']

    ciphertext = file.read().decode()  # vault:v1:xxxx

    try:
        plaintext_bytes = decrypt_data(key_name, ciphertext)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return send_file(
        io.BytesIO(plaintext_bytes),
        download_name="decrypted.txt",
        as_attachment=True,
        mimetype='application/octet-stream'
    )

if __name__ == '__main__':
    app.run(port=5000)
