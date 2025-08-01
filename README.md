# 平台各方功能介绍

## 启动

### 数据/函数提供方

``````
# 启动vault
vault server -dev
# 根据密钥修改环境变量
export VAULT_ADDR='http://127.0.0.1:9001'
export VAULT_TOKEN='hvs.xxxxxxxx'

vim ~/.bashrc
aource ~/.bashrc
# 启动transit引擎
vault secrets enable transit
# 启动服务
python -m uvicorn main:app --reload --host 0.0.0.0 --port 9001
``````

### 协调器(Coordinator)

``````
python -m uvicorn coordinator:app --reload --host 0.0.0.0 --port 5000
``````

### Tee(Trusted Execution Environment)

``````
python -m uvicorn tee:app --reload --host 0.0.0.0 --port 1000
``````

## 流程

### 主流程

发起方向数据/函数提供方发起审批请求(实际上是先给协调器发送，再由协调器转发给数据/函数提供方)

```
curl -X POST "http://127.0.0.1:5000/start_approval" \
  -H "Content-Type: application/json" \
  -d '{
    \"client_id\": \"client_001\",
    \"server_urls\": [
      \"http://127.0.0.1:9001\",
      \"http://127.0.0.1:9002\",
      \"http://127.0.0.1:9003\"
    ],
    \"content\": \"申请访问内部系统\"
  }'
```

数据/函数提供方的前端查看已审批/未审批的请求

```
# 待审批
curl -X GET "http://127.0.0.1:9001/approval/get_approvals?type=pending"
# 已审批
curl -X GET "http://127.0.0.1:9001/approval/get_approvals?type=approved"
```

数据/函数提供方人工审核后向发起方发送审核结果(实际是向服务端发送结果，再由服务端转发给协调器，协调器收齐审批后，再统一将审批结果发送给发起方)

```
curl -X POST "http://127.0.0.1:9001/approval/submit_decision" \
  -H "Content-Type: application/json" \
  -d "{
        \"client_id\": \"client_001\",
        \"result\": \"yes\"
      }"
```

审批通过后，发起方向tee发送计算请求(这个目前还没写好，目前只有解密数据功能)

```
curl -X POST http://127.0.0.1:1000/decrypt_datakey \
  -F "encrypted_key=@digital_envelope/encrypted_key.txt" \
  -F "key_name=my-sym-key1" \
  -F "client_id=client_001"
```

### 其他功能

发起方主动查询审批结果

```
curl -X GET http://127.0.0.1:5000/get_results/client_001
```

数据/函数提供方自行加密数据

```
curl -X POST http://127.0.0.1:9001/vault/encrypt_file \
  -F "file=@approval_data.zip" \
  -F "sym_key_name=my-sym-key1" \
  --output digital_envelope.zip
```
