from fastapi import FastAPI
from approval_server import app as approval_router
from vault_server import app as vault_router

import uvicorn

app = FastAPI()

# 挂载两个模块，分别加上前缀
app.include_router(approval_router, prefix="/approval", tags=["Approval Service"])
app.include_router(vault_router, prefix="/vault", tags=["Vault Service"])
