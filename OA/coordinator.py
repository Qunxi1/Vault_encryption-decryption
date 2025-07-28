from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel
import sqlite3
import httpx
import os
from typing import List, Dict
import asyncio

app = FastAPI()

# SQLite 文件路径（协调器本地）
DB_PATH = "./approval_results.db"
RESULT_TEXT_PATH = "./final_results.txt"

# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 建立approvals表
    c.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            client_id TEXT,
            server_url TEXT,
            result TEXT,
            url_count INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 请求模型
class ApprovalRequest(BaseModel):
    client_id: str
    server_urls: List[str]
    content: str

class ApprovalResult(BaseModel):
    client_id: str
    server_url: str
    result: str  # "yes" or "no"
    url_count: int

# 保存审批结果
def save_approval_result(client_id: str, server_url: str, result: str, url_count: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO approvals (client_id, server_url, result)
        VALUES (?, ?, ?)
    ''', (client_id, server_url, result, url_count))
    conn.commit()
    conn.close()

# 获取所有结果
def get_results_by_client(client_id: str) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT server_url, result FROM approvals WHERE client_id = ?
    ''', (client_id,))
    rows = c.fetchall()
    conn.close()
    return [{"server_url": row[0], "result": row[1]} for row in rows]

# 判断是否收齐所有审批
def is_all_approved(client_id: str, expected_count: int) -> bool:
    results = get_results_by_client(client_id)
    return len(results) >= expected_count

# 汇总结果并写入文本
def write_summary(client_id: str):
    results = get_results_by_client(client_id)
    with open(RESULT_TEXT_PATH, "a") as f:
        f.write(f"审批结果 for client_id={client_id}:\n")
        for item in results:
            f.write(f"{item['server_url']}: {item['result']}\n")
        f.write("\n")

# 向一个审批服务器发送请求
async def send_approval(server_url: str, client_id: str, content: str, url_count: int):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(server_url, json={
                "client_id": client_id,
                "content": content,
                "url_count": url_count
            })
    except Exception as e:
        print(f"Error contacting {server_url}: {e}")

# 主审批请求入口
'''示例
curl -X POST http://127.0.0.1:8000/start_approval \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "client_001",
    "server_urls": [
      "http://127.0.0.1:9001/approval",
      "http://127.0.0.1:9002/approval",
      "http://127.0.0.1:9003/approval"
    ],
    "content": "申请访问内部系统"
  }'

'''
@app.post("/start_approval")
async def start_approval(
	req: ApprovalRequest, 
	background_tasks: BackgroundTasks,
):
    url_count = len(req.server_urls)
    # 并发通知所有审批服务器
    for url in req.server_urls:
        background_tasks.add_task(send_approval, url, req.client_id, req.content, url_count)
    return {"status": "sent", "message": f"已向 {url_count} 个服务器发出审批请求"}

'''示例
curl -X POST http://192.168.216.128:5000/receive_result \
  -H "Content-Type: application/json" \
  -d '{ 
    "client_id": "client_001",
    "server_url": "http://192.168.216.129:9001/approval",
    "result": "yes",
    "url_count": 3
    }'
'''

# 接收审批服务器返回的结果
@app.post("/receive_result")
async def receive_result(
	result: ApprovalResult,
):
    save_approval_result(result.client_id, result.server_url, result.result, result.url_count)

    # 判断是否收齐全部结果（需要知道期望数，可简化为硬编码或另存表）
    if is_all_approved(result.client_id, result.url_count):
        write_summary(result.client_id)

    return {"status": "ok"}

# 客户端主动查询结果（可选）
'''示例
curl -X POST http://127.0.0.1:8000/receive_result \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "client_001",
    "server_url": "http://127.0.0.1:9001/approval",
    "result": "yes"
  }'
'''
@app.get("/get_results/{client_id}")
def get_results(client_id: str):
    results = get_results_by_client(client_id)
    return {"client_id": client_id, "results": results}
