import os
import requests
from pathlib import Path
from tqdm import tqdm

SERVER_URL = "http://192.168.216.128:5000"  # 修改为服务端地址
ENCRYPT_ENDPOINT = f"{SERVER_URL}/envelope/encrypt"
DECRYPT_ENDPOINT = f"{SERVER_URL}/envelope/decrypt"

# 遍历所有文件，找出最大文件
def find_largest_file_size(root_dir):
    max_size = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            path = os.path.join(dirpath, fname)
            size = os.path.getsize(path)
            if size > max_size:
                max_size = size
    return max_size

def encrypt_folder(input_dir, output_dir, key_name):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 找出最大文件尺寸
    max_size = find_largest_file_size(input_dir)
    print(f"最大文件尺寸：{max_size / 1024**2:.2f} MB")

    # 遍历所有文件并上传加密
    for root, _, files in os.walk(input_dir):
        for file in tqdm(files, desc="加密文件"):
            rel_path = Path(root).relative_to(input_dir) / file
            input_file_path = input_dir / rel_path
            with open(input_file_path, "rb") as f:
                response = requests.post(
                    ENCRYPT_ENDPOINT,
                    files={"file": (file, f)},
                    data={"sym_key_name": key_name},
                    stream=True
                )
                if response.status_code != 200:
                    print(f"[失败] 加密失败: {rel_path} => {response.text}")
                    continue

                out_zip_path = output_dir / rel_path.with_suffix(".zip")
                out_zip_path.parent.mkdir(parents=True, exist_ok=True)
                # 分块写入
                with open(out_zip_path, "wb") as out_f:
                    for chunk in response.iter_content(chunk_size=8192):
                        out_f.write(chunk)

def decrypt_folder(encrypted_dir, output_dir):
    # 提取文件所在的目录
    encrypted_dir = Path(encrypted_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 遍历目录中的zip文件(加密后输出为zip文件)
    for root, _, files in os.walk(encrypted_dir):
        for file in tqdm(files, desc="解密文件"):
            if not file.endswith(".zip"):
                continue
            rel_path = Path(root).relative_to(encrypted_dir) / file
            zip_path = encrypted_dir / rel_path

            # 解压临时保存
            from zipfile import ZipFile
            with ZipFile(zip_path, 'r') as zip_ref:
                key_name = zip_ref.read("key_name.txt").decode("utf-8").strip()  # 解码并去除空格
                files_needed = {
                    name: zip_ref.read(name)
                    for name in ['data.bin', 'luks_header.bin', 'encrypted_key.txt']
                }

            response = requests.post(
                DECRYPT_ENDPOINT,
                files={
                    "encrypted_key": ("encrypted_key.txt", files_needed["encrypted_key.txt"]),
                    "key_name": (None, key_name),
                    "encrypted_file": ("data.bin", files_needed["data.bin"]),
                    "luks_header": ("luks_header.bin", files_needed["luks_header.bin"]),
                },
                stream=True
            )
            if response.status_code != 200:
                print(f"[失败] 解密失败: {rel_path} => {response.text}")
                continue

            recovered_rel_path = rel_path.with_suffix("")  # 去掉 .zip
            out_file_path = output_dir / recovered_rel_path
            out_file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(out_file_path, "wb") as out_f:
                for chunk in response.iter_content(chunk_size=8192):
                    out_f.write(chunk)
