from fastapi import FastAPI, File, UploadFile, Form, HTTPException
import os, base64, requests, zipfile
import subprocess
import tempfile
import traceback

app = FastAPI()

VAULT_PROVIDER_URL = "http://192.168.216.129:9001/vault/decrypt_key"

# 使用本地明文 DEK 对加密数据进行 LUKS 解密
def luks_decrypt_data(encrypted_zip_path: str, plaintext_key_path: str, output_path: str):
    try:
        # 读取明文 DEK
        with open(plaintext_key_path, "rb") as f:
            plaintext_dek = f.read()
        plaintext_dek = base64.b64decode(plaintext_dek)
        # 打开加密压缩包并提取相应文件
        with zipfile.ZipFile(encrypted_zip_path, "r") as z:   
            # 读取密文文件
            with z.open("data.bin") as f:
                encrypted_content = f.read()
            # 读取 luks_header
            with z.open("luks_header.bin") as f:
                luks_header = f.read()

        # 保存密文（LUKS 块设备）到临时文件
        with tempfile.TemporaryDirectory() as tmpdir:
            luks_data_path = os.path.join(tmpdir, "data.img")
            luks_header_path = os.path.join(tmpdir, "header.bin")
            plain_path = os.path.join(tmpdir, "recovered_output.bin")

            # 提取文件实际大小的密文
            # 提取前8字节为明文大小（大端）
            file_size = int.from_bytes(encrypted_content[:8], byteorder="big")
            # 提取真正的密文部分
            ciphertext = encrypted_content[8:]
            with open(luks_data_path, "wb") as f:
                f.write(ciphertext)
            with open(luks_header_path, "wb") as f:
                f.write(luks_header)

            subprocess.run([
                "cryptsetup", "open",
                "--header", luks_header_path,
                luks_data_path, "luks_tmp",
                "--key-file", "-"
            ], input=plaintext_dek, check=True)

            subprocess.run(["dd", f"if=/dev/mapper/luks_tmp", f"of={plain_path}", "bs=1M"], check=True)

            subprocess.run(["cryptsetup", "close", "luks_tmp"], check=True)

            with open(plain_path, "rb") as f:
                decrypted_data = f.read(file_size)
            with open(output_path, "wb") as f:
                f.write(decrypted_data)

        print(f"解密完成，结果已保存到: {output_path}")
        return output_path
    except Exception as e:
        print(f"解密失败: {e}")
        traceback.print_exc()
        raise

'''示例
curl -X POST http://192.168.216.130:1000/decrypt_datakey \
  -F "encrypted_key=@digital_envelope/encrypted_key.txt" \
  -F "key_name=my-sym-key1" \
  -F "client_id=client_001"
'''
#向数据/函数提供方请求解密密钥
@app.post("/decrypt_datakey")
async def request_decryption_key(
    encrypted_key: UploadFile = File(...),
    key_name: str = Form(...),
    client_id: str = Form(...),
):
    try:
        files = {
            "encrypted_key": (encrypted_key.filename, await encrypted_key.read()),
        }
        data = {
            "key_name": key_name,
            "client_id": client_id
        }

        # 向数据/函数提供方发送请求
        resp = requests.post(VAULT_PROVIDER_URL, files=files, data=data)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"请求解密密钥失败: {resp.text}")

        # 将明文密钥保存到文件
        plaintext_key_path = "plaintext_key.txt"
        with open(plaintext_key_path, "wb") as f:
            f.write(resp.content)

        return {"message": "解密密钥请求成功", "plaintext_key_path": plaintext_key_path}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TEE 请求密钥出错: {str(e)}")
