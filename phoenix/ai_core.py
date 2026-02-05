import config
import sys
import os
from openai import OpenAI
base=config.SYSTEM_INSTRUCTION_CN

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

class AI_CORE:
    def __init__(self):
        self.client=OpenAI(
            api_key=config.API_KEY,
            base_url=config.API_BASE)
        self.init_history()
        
    def init_history(self):
        self.history = [{"role": "system", "content": base}]
    
    def trim_history(self):
        if len(self.history)>21:
            self.history=[self.history[0]+self.history[-20:]]

    def reset_memory(self):
        self.init_history()

    def chat(self,user_content):
        self.history.append({"role":"user","content":user_content})
        self.trim_history()
        user_model=config.MODEL_CHEAP
        if(len(user_content)>15):
            user_model=config.MODEL_SMART
        
        try:
            response=self.client.chat.completions.create(
                model=user_model,
                messages=self.history,
                temperature=1.1,
                max_tokens=10000
            )
            answer=response.choices[0].message.content
            status = "normal"
            if "[FATAL_ERROR:SYSTEM_LOCK]" in answer:
                status = "shutdown"
                # 移除回复中的标识符，不让用户看到原始标记
                answer = answer.replace("[FATAL_ERROR:SYSTEM_LOCK]", "").strip()
            self.history.append({"role":"assistant","content":answer})
            self.trim_history()
            return answer,status
        except Exception as e:
            print(f"API Error: {e}") # 建议打印错误到控制台方便调试
            return f"联络失败。错误：{e},请检查token余量或者联系作者。","error"
        




