from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
import requests, base64, io, os, zipfile
from config import VAULT_ADDR, VAULT_TOKEN
import subprocess
import tempfile
# 调试包
import traceback
from pydantic import BaseModel
from datetime import datetime
import sqlite3
from typing import Literal

app = FastAPI()

VAULT_TRANSIT_PATH = "transit"
HEADERS = {"X-Vault-Token": VAULT_TOKEN}
# 数据库文件路径
DB_PATH = "./approval_data.db"

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
    使用 LUKS 加密大文件（不使用 losetup，避免对齐和额外空间），返回密文和独立 header
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        plain_path = os.path.join(tmpdir, "plain_data.bin")
        luks_data_path = os.path.join(tmpdir, "luks_data.img")
        luks_header_path = os.path.join(tmpdir, "luks_header.bin")

        # 保存明文文件并计算文件实际大小
        with open(plain_path, "wb") as f:
            f.write(plaintext)
        file_size = len(plaintext)

        # 创建与明文等长的密文块设备，并手动512字节对齐
        remainder = file_size % 512
        if remainder != 0:
            padding = 512 - remainder
        else:
            padding = 0

        with open(luks_data_path, "wb") as f:
            f.write(b"\x00" * (file_size + padding))

        # 1. 初始化 luksFormat，直接作用于文件
        subprocess.run([
            "cryptsetup", "luksFormat",
            "--type", "luks2",
            "--header", luks_header_path,
            "--batch-mode",
            luks_data_path,
            "--key-file", "-"
        ], input=dek, check=True)

        # 2. 打开 luks 文件
        subprocess.run([
            "cryptsetup", "open",
            "--header", luks_header_path,
            luks_data_path, "luks_tmp",
            "--key-file", "-"
        ], input=dek, check=True)

        # 3. 写入明文
        subprocess.run(["dd", f"if={plain_path}", "of=/dev/mapper/luks_tmp", "bs=1M", "status=none"], check=True)

        # 4. 关闭 luks 设备
        subprocess.run(["cryptsetup", "close", "luks_tmp"], check=True)

        # 5. 读取密文和 header
        with open(luks_data_path, "rb") as f:
            encrypted_data = f.read()
        with open(luks_header_path, "rb") as f:
            header_data = f.read()

        # 使用 int.to_bytes() 写入前 8 字节表示明文长度（大端）
        encrypted_data = file_size.to_bytes(8, byteorder="big") + encrypted_data
        return encrypted_data, header_data

# ---------- Approval函数 ----------
# 启动时初始化数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            client_id TEXT PRIMARY KEY,
            content TEXT,
            base_apiurl TEXT,
            timestart TEXT,
            result TEXT,
            status INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 协调器会发来的数据格式
class ApprovalContent(BaseModel):
    client_id: str
    content: str
    base_apiurl: str
# 前端发送审批结果的数据格式
class ApprovalResult(BaseModel):
    client_id: str
    result: str
# ---------- API ----------
'''示例
# 加密生成数字信封
curl -X POST http://localhost:5000/envelope/encrypt_file \
  -F "file=@bigfile.tar.gz" \
  -F "sym_key_name=my-sym-key" \
  --output digital_envelope.zip
'''
@app.post("/envelope/encrypt_file")
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
curl -X POST http://localhost:5000/envelope/decrypt_key \
  -F "encrypted_key=@encrypted_key.txt" \
  -F "key_name=my-sym-key" \
  --output plaintext_key.txt
'''
@app.post("/envelope/decrypt_key")
async def decrypt_key(
    encrypted_key: UploadFile = File(...),        # 加密后的DEK
    key_name: str = Form(...),              # 根密钥名
    client_id: str = Form(...),
):
    try:
        # === 检查审批结果 ===
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT result FROM approvals WHERE client_id = ?", (client_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return JSONResponse(status_code=200, content={
                "status": "rejected",
                "message": "未找到审批记录，无法解密"
            })
        if row[0].lower() != "yes":
             return JSONResponse(status_code=200, content={
                "status": "rejected",
                "message": "审批未通过，无法解密"
            })

        # 获取加密后的对称密钥
        encrypted_dek = (await encrypted_key.read()).decode()

        # 解密出明文 DEK
        url = f"{VAULT_ADDR}/v1/{VAULT_TRANSIT_PATH}/decrypt/{key_name}"
        resp = requests.post(url, headers=HEADERS, json={"ciphertext": encrypted_dek})
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"RSA解密失败: {resp.text}")
        plaintext_dek_b64 = resp.json()["data"]["plaintext"]
        file_content = f"{plaintext_dek_b64}"
        file_like = io.BytesIO(file_content.encode("utf-8"))

        return StreamingResponse(
            file_like,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=plaintext_key.txt"}
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


# 审批服务器接收协调器发来的请求
@app.post("/approval")
async def receive_approval(
    data: ApprovalContent,
):
    timestart = datetime.now().isoformat()

    # 写入 SQLite 数据库
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO approvals (client_id, content, base_apiurl, timestart)
        VALUES (?, ?, ?, ?)
    ''', (data.client_id, data.content, data.base_apiurl, timestart))
    conn.commit()
    conn.close()

    print(f"收到来自 {data.client_id} 的审批请求：{data.content}")
    return {"status": "received", "message": "审批请求已保存"}

'''示例
curl -X GET "http://localhost:8000/get_approvals?type=pending"
'''
# 接收前端的数据库查看请求
@app.get("/get_approvals")
async def get_approvals(type: Literal["pending", "approved"]):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if type == "pending":
        c.execute("SELECT * FROM approvals WHERE status = 0")
    else:
        c.execute("SELECT * FROM approvals WHERE status = 1")
    rows = c.fetchall()
    conn.close()
    
    # 将结果封装成字典列表
    result = []
    for row in rows:
        result.append({
            "client_id": row[0],
            "content": row[1],
            "base_apiurl": row[2],
            "timestart": row[3],
            "result": row[4],
            "status": row[5],
        })
    
    return {"count": len(result), "data": result}

'''示例
curl -X POST "http://localhost:8000/submit_result" \
  -H "Content-Type: application/json" \
  -d '{
        "client_id": "client_001",
        "result": "yes"
      }'
'''
# 接收前端数据库审批请求
@app.post("/submit_decision")
async def submit_result(
    data: ApprovalResult,
    request: Request,
):
    # 获取当前服务器的fastapi的服务地址
    server_url = str(request.base_url)
    # 向本地数据库写入审批结果
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 提取协调器地址
    c.execute('''
        SELECT base_apiurl FROM approvals WHERE client_id = ?
        ''', (data.client_id,))
    row = c.fetchone()
    url = row[0]
    url = url + "receive_result"

    c.execute('''
        UPDATE approvals
        SET result = ?, status = 1
        WHERE client_id = ?
    ''', (data.result, data.client_id))
    conn.commit()
    conn.close()
    # 将审批数据发给协调器
    # 构造发送给协调器的数据
    headers = {
        "client_id": data.client_id,
        "server_url": server_url,
        "result": data.result
    }
    r = requests.post(url, json=headers)
    if r.status_code != 200:
        raise RuntimeError(f"发送审批结果失败，协调器返回: {r.text}")
    # Vault 返回的 plaintext 是 base64 编码过的，要解码成真正的 bytes 密钥
    return {"status": "ok", "message": f"审批结果已更新为：{data.result}"}

