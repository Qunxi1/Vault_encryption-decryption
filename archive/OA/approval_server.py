from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime
import os
import sqlite3
from typing import Literal

app = FastAPI()

# 数据库文件路径
DB_PATH = "./approval_data.db"

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
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE approvals
        SET result = ?, status = 1
        WHERE client_id = ?
    ''', (data.result, data.client_id))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"审批结果已更新为：{data.result}"}
