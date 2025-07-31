# 平台各方功能介绍

## 数据/函数提供方

<details>
<summary>点击展开</summary>

### 启动

``````
# 启动vault
vault server -dev
# 启动transit引擎
vault secrets enable transit
# 启动服务
python -m uvicorn main:app --reload --host 0.0.0.0 --port 9001
``````

`main.py` 把审批器和vault加解密服务分别挂载在前缀为 `/approval` 和 `/vault` 的请求下

### 提供的服务

#### 审批器( `/approval` )

<details>
<summary>点击展开</summary>

##### 接收协调器(coordinator)发来的审批请求

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

##### 数据库查看请求

**功能**：前端向审批器发送数据库查看请求，查看已审批/待审批的审批信息，方便前端展示。

`pending` : 待审批	`approved` : 已审批

```
# 待审批
curl -X GET "http://127.0.0.1:9001/approval/get_approvals?type=pending"
# 已审批
curl -X GET "http://127.0.0.1:9001/approval/get_approvals?type=approved"
```

##### 接受前端审批请求

**功能**：前端人工进行审批后，将审批结果传给审批服务器，审批服务器本地保存审批结果信息后会主动传回协调器，再由协调器统计所有审批服务器的审批结果，并将整个任务的审批结果发送给客户端

```
curl -X POST "http://127.0.0.1:9001/approval/submit_decision" \
  -H "Content-Type: application/json" \
  -d "{
        \"client_id\": \"client_001\",
        \"result\": \"yes\"
      }"
```

</details>

#### Vault加密解密服务( `/vault` )

<details>
<summary>点击展开</summary>

##### `Luks` 加密文件

**功能** ：前端发送加密文件请求，将相应路径的文件进行本地 `Luks` 加密，并返回 `zip` 包。

由于目前是处于模拟阶段所以发送的是文件，但其实文件就在服务器本地并不需要传输，给路径即可

```
curl -X POST http://127.0.0.1:9001/vault/encrypt_file \
  -F "file=@approval_data.zip" \
  -F "sym_key_name=my-sym-key1" \
  --output digital_envelope.zip
```

##### 解密 `data key` 

**功能** ：发起方审批完成并通过后，给 `tee` 发送计算请求， `tee` 会去指定位置拿取数据/函数密文数据，之后向数据/函数提供方发送 `data key` 解密请求，解密完成后发送明文密钥给 `tee` ，再由 `tee` 进行本地解密

```
curl -X POST http://127.0.0.1:9001/vault/decrypt_key \
  -F "encrypted_key=@digital_envelope/encrypted_key.txt" \
  -F "key_name=my-sym-key1" \
  -F "client_id=client_001" \
  --output plaintext_key.txt
```

</details>

</details>

## 协调器(Coordinator)

<details>
<summary>点击展开</summary>

协调器旨在转发发起方的审批请求，并接收审批服务器的审批结果并发送给发起方

### 启动

``````
python -m uvicorn coordinator:app --reload --host 0.0.0.0 --port 5000
``````

### 提供的服务

#### 转发发起方的审批请求

**功能**：将收到的发起方审批请求转发给指定的各个审批方审批，并将审批信息存到本地数据库

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

#### 接受审批服务器返回的审批结果

**功能**：审批服务器审批完成后，将结果主动返回给协调器，并进行统计是否所有审批方审批完成，审批完成后，根据各方的审批结果给发起方返回一个最终结果。

若有一方审批未通过，则该任务审批不通过

```
curl -X POST "http://127.0.0.1:5000/receive_result" \
  -H "Content-Type: application/json" \
  -d "{
        \"client_id\": \"client_001\",
        \"server_url\": \"127.0.0.1:9001\",
        \"result\": \"yes\"
      }"
```

#### 发起方主动查询审批结果

**功能**：发起方主动查询审批结果，可用于审批结果刷新或者重新审批等功能

```
curl -X GET http://127.0.0.1:5000/get_results/client_001
```

</details>

## Tee(Trusted Execution Environment)

<details>
<summary>点击展开</summary>

发起方审批完成后，向tee发送计算请求，tee先从中央服务器拿到数据/函数密文后，向数据/函数提供方发送解密data key请求，返回密钥明文后，本地进行解密

### 启动

``````
python -m uvicorn tee:app --reload --host 0.0.0.0 --port 1000
``````

### 提供的服务

#### 申请解密密钥

**功能**：向数据/函数提供方发送解密data key请求

实际上这个功能不应该被做成是一个独立的请求，应该作为一个普通函数，在发起计算的请求中调用，但目前并没有tee环境，所以就将该请求模拟成发起请求

```
curl -X POST http://127.0.0.1:1000/decrypt_datakey \
  -F "encrypted_key=@digital_envelope/encrypted_key.txt" \
  -F "key_name=my-sym-key1" \
  -F "client_id=client_001"
```

#### `Luks` 解密文件

**功能**：返回明文 `data key` 后，将相应数据进行解密。

该功能就是一个普通函数，并不是http请求，也是在发起tee计算的请求中调用，用于解密要进行计算的数据和用于计算的函数

```
'''
encrypted_file_path:密文文件路径
plaintext_key_path：明文密钥路径
output_path：解密后文件的输出路径
目前这只是简单的解密函数，因为后续密文数据都是存在zip压缩包中，因而后续的密文文件和代码中写死的 luks_header 等路径的参数都会进行修改
'''
luks_decrypt_data(encrypted_file_path, plaintext_key_path, output_path)
```

</details>
