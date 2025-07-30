from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime
import os, requests
import sqlite3
from typing import Literal
from config import VAULT_ADDR, VAULT_TOKEN, DB_PATH

app = APIRouter()

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