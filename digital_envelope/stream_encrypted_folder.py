import os
import requests

def upload_folder(folder_path, key_name):
    # url = "http://localhost:5000/envelope/encrypt-folder"
    url = "http://192.168.216.128:5000/envelope/encrypt-folder"
    files = []
    paths = []
    for root, _, filenames in os.walk(folder_path):
        for fname in filenames:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, folder_path)
            files.append(("files", (rel_path, open(full_path, "rb"), "application/octet-stream")))
            paths.append(rel_path)

    data = {"sym_key_name": key_name}
    for i, p in enumerate(paths):
        data[f"paths"] = paths  # 直接传整个路径列表

    resp = requests.post(url, files=files, data=data)
    with open("encrypted_folder.zip", "wb") as f:
        f.write(resp.content)

upload_folder("myfolder", "my-sym-key")
