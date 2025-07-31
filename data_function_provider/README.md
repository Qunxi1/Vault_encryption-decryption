# 数据/函数提供方

数据/函数提供方提供两个服务：

- 审批( `approval_server.py` )
- 本地数据加密和对 `tee` 的 `data_key` 解密请求(vault_server.py)

## 如何启动服务

我们用 `man.py` 文件进行启动多个服务文件，它们会共用一个端口，启动命令：

``````
python -m uvicorn main:app --reload --host 0.0.0.0 --port 9001
``````

`main.py` 把审批器和vault加解密服务分别挂载在前缀为 `/approval` 和 `/vault` 的请求下

## 提供的服务

### 审批器( `/approval` )

#### 接收协调器(coordinator)发来的审批请求

**功能**：此请求是协调器内部自动对审批器发送的请求，不需要人为请求。

将审批信息和提交时间存入本地数据库中

```
curl -X POST http://127.0.0.1:9001/approval/approval \
 -H "Content-Type: application/json" \
 -d "{
 	 \"client_id\": \"client_001\", 
 	 \"content\": \"申请访问内部系统\",
 	 \"base_apiurl\": \"http://127.0.0.1:5000/\"
 	 }"
```

#### 数据库查看请求

**功能**：前端向审批器发送数据库查看请求，查看已审批/待审批的审批信息，方便前端展示。

`pending` : 待审批	`approved` : 已审批

```
# 待审批
curl -X GET "http://127.0.0.1:9001/approval/get_approvals?type=pending"
# 已审批
curl -X GET "http://127.0.0.1:9001/approval/get_approvals?type=approved"
```

#### 接受前端审批请求

**功能**：前端人工进行审批后，将审批结果传给审批服务器，审批服务器本地保存审批结果信息后会主动传回协调器，再由协调器统计所有审批服务器的审批结果，并将整个任务的审批结果发送给客户端

```
curl -X POST "http://127.0.0.1:9001/approval/submit_decision" \
  -H "Content-Type: application/json" \
  -d "{
        \"client_id\": \"client_001\",
        \"result\": \"yes\"
      }"
```

### Vault加密解密服务( `/vault` )

#### `Luks` 加密文件

**功能** ：前端发送加密文件请求，将相应路径的文件进行本地 `Luks` 加密，并返回 `zip` 包。

由于目前是处于模拟阶段所以发送的是文件，但其实文件就在服务器本地并不需要传输，给路径即可

```
curl -X POST http://127.0.0.1:9001/vault/encrypt_file \
  -F "file=@approval_data.zip" \
  -F "sym_key_name=my-sym-key1" \
  --output digital_envelope.zip
```

#### 解密 `data key` 

**功能** ：发起方审批完成并通过后，给 `tee` 发送计算请求， `tee` 会去指定位置拿取数据/函数密文数据，之后向数据/函数提供方发送 `data key` 解密请求，解密完成后发送明文密钥给 `tee` ，再由 `tee` 进行本地解密

```
curl -X POST http://127.0.0.1:9001/vault/decrypt_key \
  -F "encrypted_key=@digital_envelope/encrypted_key.txt" \
  -F "key_name=my-sym-key1" \
  -F "client_id=client_003" \
  --output plaintext_key.txt
```

