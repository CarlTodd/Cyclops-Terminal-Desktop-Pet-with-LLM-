from gui import CyclopsWindow
import os
import sys

# 获取 EXE 所在的文件夹路径
if hasattr(sys, 'frozen'):
    # 如果是打包后的环境
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是普通的 .py 环境
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 定义一个获取本地路径的函数
def local_path(filename):
    return os.path.join(BASE_DIR, filename)


if __name__ == "__main__":
    CyclopsWindow()
    