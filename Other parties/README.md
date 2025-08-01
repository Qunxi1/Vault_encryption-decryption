# 协调器(Coordinator)

<details>
<summary>点击展开</summary>

协调器旨在转发发起方的审批请求，并接收审批服务器的审批结果并发送给发起方

## 如何启动服务

``````
python -m uvicorn coordinator:app --reload --host 0.0.0.0 --port 5000
``````

## 提供的服务

### 转发发起方的审批请求

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

### 接受审批服务器返回的审批结果

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

### 发起方主动查询审批结果

**功能**：发起方主动查询审批结果，可用于审批结果刷新或者重新审批等功能

```
curl -X GET http://127.0.0.1:5000/get_results/client_001
```

</details>

# Tee(Trusted Execution Environment)

<details>
<summary>点击展开</summary>

发起方审批完成后，向tee发送计算请求，tee先从中央服务器拿到数据/函数密文后，向数据/函数提供方发送解密data key请求，返回密钥明文后，本地进行解密

## 如何启动服务

``````
python -m uvicorn tee:app --reload --host 0.0.0.0 --port 1000
``````

## 提供的服务

### 申请解密密钥

**功能**：向数据/函数提供方发送解密data key请求

实际上这个功能不应该被做成是一个独立的请求，应该作为一个普通函数，在发起计算的请求中调用，但目前并没有tee环境，所以就将该请求模拟成发起请求

```
curl -X POST http://127.0.0.1:1000/decrypt_datakey \
  -F "encrypted_key=@digital_envelope/encrypted_key.txt" \
  -F "key_name=my-sym-key1" \
  -F "client_id=client_001"
```

### `Luks` 解密文件

**功能**：返回明文 `data key` 后，将相应数据进行解密。

该功能就是一个普通函数，并不是http请求，也是在发起tee计算的请求中调用，用于解密要进行计算的数据和用于计算的函数

```
'''
encrypted_zip_path: 密文文件zip包的路径
plaintext_key_path: 明文密钥路径
output_path: 解密后文件的输出路径
'''
luks_decrypt_data(encrypted_zip_path, plaintext_key_path, output_path)
```

</details>
