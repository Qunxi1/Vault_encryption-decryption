from stream_encrypted_folder import encrypt_folder, decrypt_folder

'''# 示例路径
input_dir = "/path/to/your/large_folder"
encrypted_output_dir = "/path/to/encrypted_output"
decrypted_output_dir = "/path/to/decrypted_output"
'''
input_dir = "D:/1/test"
encrypted_output_dir = "D:/1/test_encrypted"
decrypted_output_dir = "D:/1/test_decrypted"
key_name = "my_sym_key"

# 加密整个文件夹
encrypt_folder(input_dir, encrypted_output_dir, key_name)

# 解密还原
decrypt_folder(encrypted_output_dir, decrypted_output_dir)
