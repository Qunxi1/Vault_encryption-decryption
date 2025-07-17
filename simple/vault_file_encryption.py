import requests
import base64

VAULT_ADDR = "http://127.0.0.1:8200"
VAULT_TOKEN = "hvs.ZwQfacF3d4WQbzKuSmeziDpx"  # 你自己的 Vault token

HEADERS = {
    "X-Vault-Token": VAULT_TOKEN
}
'''
requests.post(f"{VAULT_ADDR}/v1/sys/mounts/transit", headers=HEADERS, json={
    "type": "transit"
})'''

key_name = "my-key"

resp = requests.post(f"{VAULT_ADDR}/v1/transit/keys/{key_name}", headers=HEADERS)
print(f"resp{resp}")
if resp.status_code == 200:
    print("密钥创建成功")
else:
    print(f"出错: {resp.status_code} {resp.text}")

# 加密
with open("test.txt", "rb") as f:
    file_data = f.read()
b64_plaintext = base64.b64encode(file_data).decode()

resp = requests.post(f"{VAULT_ADDR}/v1/transit/encrypt/{key_name}",
                     headers=HEADERS,
                     json={"plaintext": b64_plaintext})

ciphertext = resp.json()["data"]["ciphertext"]
with open("test.txt.enc", "w") as f:
    f.write(ciphertext)
print("密文保存在:text.txt.enc")

# 解密
with open("test.txt.enc", "r") as f:
    ciphertext = f.read().strip()
resp = requests.post(f"{VAULT_ADDR}/v1/transit/decrypt/{key_name}",
                     headers=HEADERS,
                     json={"ciphertext": ciphertext})

b64_decrypted = resp.json()["data"]["plaintext"]
decrypted = base64.b64decode(b64_decrypted)
with open("test_decrypted.txt", "wb") as f:
    f.write(decrypted)
print("解密完成，文件还原为:text_decrypted.txt")

# 设置成可删除状态
resp = requests.post(
    f"{VAULT_ADDR}/v1/transit/keys/{key_name}/config",
    headers=HEADERS,
    json={"deletion_allowed": True}
)
print(f"resp{resp}")
if resp.status_code == 200:
    print("deletion_allowed 设置成功")
else:
    print("设置失败:", resp.text)
# 删除密钥
resp = requests.delete(
    f"{VAULT_ADDR}/v1/transit/keys/{key_name}",
    headers=HEADERS
)
print(f"resp{resp}")
if resp.status_code == 204:
    print("密钥删除成功")
else:
    print("删除失败:", resp.text)