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

# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 建立approvals表
    c.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            client_id TEXT PRIMARY KEY,
            total_count int,
            receive_count int,
            final_result TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS approval_results (
            client_id TEXT,
            server_url TEXT,
            result TEXT,
            PRIMARY KEY (client_id, server_url),
            FOREIGN KEY(client_id) REFERENCES approval_tasks(client_id)
        );
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
        INSERT INTO approval_results (client_id, server_url, result)
        VALUES (?, ?, ?)
    ''', (client_id, server_url, result))
    c.execute('''
        UPDATE approvals
        SET receive_count = receive_count + 1
        WHERE client_id = ?
    ''', (client_id,))
    conn.commit()
    conn.close()

# 获取所有结果
def get_results_by_client(client_id: str) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT server_url, result FROM approval_results WHERE client_id = ?
    ''', (client_id,))
    rows = c.fetchall()
    conn.close()
    return [{"server_url": row[0], "result": row[1]} for row in rows]

# 判断是否收齐所有审批
def is_all_approved(client_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT total_count, receive_count FROM approvals WHERE client_id = ?
    ''', (client_id,))
    row = c.fetchone()
    conn.close()
    total_count, receive_count = row
    return total_count == receive_count

# 汇总结果并写入数据库
def write_summary(client_id: str):
    results = get_results_by_client(client_id)
    final_result = "yes"
    for item in results:
        if item['result'] == "no":
            final_result = "no"
            break
    # 将结果写入数据库
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE approvals
        SET final_result = ?
        WHERE client_id = ?
    ''', (final_result, client_id))
    conn.commit()
    conn.close()


# 向一个审批服务器发送请求
async def send_approval(server_url: str, client_id: str, content: str, base_apiurl: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(server_url, json={
                "client_id": client_id,
                "content": content,
                "base_apiurl": base_apiurl
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
      "http://127.0.0.1:9001",
      "http://127.0.0.1:9002",
      "http://127.0.0.1:9003"
    ],
    "content": "申请访问内部系统"
  }'

'''
@app.post("/start_approval")
async def start_approval(
	req: ApprovalRequest, 
	background_tasks: BackgroundTasks,
    request: Request,
):
    # 往主表插入任务信息
    url_count = len(req.server_urls)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO approvals (client_id, total_count, receive_count)
        VALUES (?, ?, 0)
    ''', (req.client_id, url_count))

    # 获取当前服务器的fastapi的服务地址
    base_apiurl = str(request.base_url)
    # 并发通知所有审批服务器
    for url in req.server_urls:
        # 往子表插入审批服务器信息
        c.execute('''
            INSERT INTO approval_results (client_id, server_url)
            VALUES (?, ?)
        ''', (req.client_id, url))
        full_url = url + "/approval"
        background_tasks.add_task(send_approval, full_url, req.client_id, req.content, base_apiurl)
    conn.commit()
    conn.close()
    return {"status": "sent", "message": f"已向 {url_count} 个服务器发出审批请求"}

'''示例
curl -X POST http://192.168.216.128:5000/receive_result \
  -H "Content-Type: application/json" \
  -d '{ 
    "client_id": "client_001",
    "server_url": "http://192.168.216.129:9001",
    "result": "yes"
    }'
'''

# 接收审批服务器返回的结果
@app.post("/receive_result")
async def receive_result(
	result: ApprovalResult,
):
    save_approval_result(result.client_id, result.server_url, result.result)

    # 判断是否收齐全部结果（并将最终结果写入数据库）
    if is_all_approved(result.client_id):
        write_summary(result.client_id)

    return {"status": "ok"}

# 客户端主动查询结果（可选）
'''示例
curl -X GET http://127.0.0.1:8000/get_results/client_001
'''
@app.get("/get_results/{client_id}")
def get_results(client_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT final_result FROM approvals WHERE client_id = ?
    ''', (client_id,))
    result = c.fetchone()
    conn.close()
    return {"client_id": client_id, "results": result}
