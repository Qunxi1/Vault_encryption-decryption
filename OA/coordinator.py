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
            timestart TEXT
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

# 保存审批结果
def save_approval_result(client_id: str, server_url: str, result: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO approvals (client_id, server_url, result)
        VALUES (?, ?, ?)
    ''', (client_id, server_url, result))
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
async def send_approval(server_url: str, client_id: str, content: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(server_url, json={
                "client_id": client_id,
                "content": content
            })
    except Exception as e:
        print(f"Error contacting {server_url}: {e}")

# 主审批请求入口
@app.post("/start_approval")
async def start_approval(
	req: ApprovalRequest, 
	background_tasks: BackgroundTasks,
):
    # 并发通知所有审批服务器
    for url in req.server_urls:
        background_tasks.add_task(send_approval, url, req.client_id, req.content)
    return {"status": "sent", "message": f"已向 {len(req.server_urls)} 个服务器发出审批请求"}

# 接收审批服务器返回的结果
@app.post("/receive_result")
async def receive_result(
	result: ApprovalResult,
):
    save_approval_result(result.client_id, result.server_url, result.result)

    # 判断是否收齐全部结果（需要知道期望数，可简化为硬编码或另存表）
    expected_count = 1  # 你也可以做成可配置项或另存一张表
    if is_all_approved(result.client_id, expected_count):
        write_summary(result.client_id)

    return {"status": "ok"}

# 客户端主动查询结果（可选）
@app.get("/get_results/{client_id}")
def get_results(client_id: str):
    results = get_results_by_client(client_id)
    return {"client_id": client_id, "results": results}
