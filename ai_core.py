import asyncio
import base64
import json
import os
import pygetwindow as gw
from openai import OpenAI
import config
import random
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


# 尝试导入 Windows 媒体控制组件
try:
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SessionManager
    WINSDK_AVAILABLE = True
except ImportError:
    WINSDK_AVAILABLE = False

class AICore:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.API_KEY,
            base_url=config.API_BASE
        )
        self.user_rules = self.load_rules()
        self.current_lang = "CN" # 默认中文
        self.init_history()
        self.last_artist = ""

    def init_history(self):
        """根据当前语言初始化历史记录的第一条（系统提示词）"""
        # 选择对应语言的基础提示词
        base = config.SYSTEM_INSTRUCTION_CN if self.current_lang == "CN" else config.SYSTEM_INSTRUCTION_EN
        
        # 加上用户规则 (rules.json)
        if self.user_rules:
            rules_str = "\n".join([f"- {r}" for r in self.user_rules])
            base += f"\n\n<user_corrections>\n{rules_str}\n</user_corrections>"
        
        # 如果历史记录已存在，则只更新第一条；否则新建
        if hasattr(self, 'history') and len(self.history) > 0:
            self.history[0] = {"role": "system", "content": base}
        else:
            self.history = [{"role": "system", "content": base}]

    def switch_language(self, lang_code):
        """切换语言的方法"""
        if lang_code in ["CN", "EN"]:
            self.current_lang = lang_code
            self.init_history()
            return True
        return False

    def load_rules(self):
        if os.path.exists("rules.json"):
            try:
                with open(local_path("rules.json"), "r", encoding="utf-8") as f:
                    return json.load(f)
            except: return []
        return []


    def _trim_history(self):
        if len(self.history) > 11:
            self.history = [self.history[0]] + self.history[-10:]

    def reset_memory(self):
        self.init_history()

    def chat(self, user_text):
        """修改后的普通对话模式"""
        # 1. 尝试从输入中提取规则 (静默执行)
        new_rule = self.extract_and_apply_rule(user_text)
        
        # 2. 正常对话逻辑
        self.history.append({"role": "user", "content": user_text})
        
        # 路由逻辑保持不变...
        use_model = config.MODEL_CHEAP
        if len(user_text) > 10: use_model = config.MODEL_SMART

        try:
            response = self.client.chat.completions.create(
                model=use_model,
                messages=self.history,
                temperature=0.8
            )
            answer = response.choices[0].message.content
            # --- 关键：检测特殊标识符 ---
            status = "normal"
            if "[FATAL_ERROR:SYSTEM_LOCK]" in answer:
                status = "shutdown"
                # 移除回复中的标识符，不让用户看到原始标记
                answer = answer.replace("[FATAL_ERROR:SYSTEM_LOCK]", "").strip()
            
            # 如果刚才提取到了新规则，可以在回复中稍微体现一下
            if new_rule:
                answer = f"（用户偏好已更新：{new_rule}）\n" + answer

            self.history.append({"role": "assistant", "content": answer})
            self._trim_history()
            return answer, status
            
        except Exception as e:
            return f"通讯异常: {e}，\n请检查token余量或者联系作者。", "error"

    def analyze_image(self, image_path, prompt_text="分析当前屏幕内容。"):
        """视觉分析模式"""
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            
            response = self.client.chat.completions.create(
                model=config.MODEL_CHEAP,
                messages=[
                    self.history[0], 
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                        ]
                        
                    }
                ],
                max_tokens=5000, 
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"*（视觉模块故障）* Visor Error: {str(e)}"

    # === 媒体获取逻辑 ===

    async def _get_media_from_system(self):
        """异步：从系统 SMTC 获取"""
        if not WINSDK_AVAILABLE: return None
        try:
            sessions = await SessionManager.request_async()
            current_session = sessions.get_current_session()
            if current_session:
                info = await current_session.try_get_media_properties_async()
                if info and info.title:
                    return {"title": info.title, "artist": info.artist or "未知艺术家"}
        except: pass
        return None

    def get_current_media_info(self):
        """同步包装器：获取当前播放信息"""
        # 1. 尝试系统 API
        sys_info = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            sys_info = loop.run_until_complete(self._get_media_from_system())
            loop.close()
        except: pass

        if sys_info: return sys_info

        # 2. 尝试窗口标题扫描 (兜底)
        try:
            titles = gw.getAllTitles()
            blacklist = ["Visual Studio", "Chrome", "Edge", "Settings", "设置", "资源管理器", "Python"]
            for t in titles:
                t = t.strip()
                if not t or t in blacklist: continue
                # 特异性匹配网易云
                if "网易云音乐" in t and " - " in t:
                    parts = t.split(" - ")
                    return {"title": parts[0].strip(), "artist": parts[1].strip()}
                # 通用匹配
                if " - " in t:
                    parts = t.split(" - ")
                    if len(parts) == 2 and len(parts[0]) > 1 and len(parts[1]) > 1:
                         if not any(b in t for b in blacklist):
                            return {"title": parts[0].strip(), "artist": parts[1].strip()}
        except: pass
        return None

    def comment_on_music(self, title, artist):
        """让 AI 评价音乐或视频音轨 (加入随机切入点与连听/视频检测)"""
        try:
            # === 0. 预处理：判断是音乐还是视频 ===
            # 常见的未知艺术家标识，根据你的播放器插件实际返回调整
            unknown_markers = ["未知艺术家","未知","Unknown Artist", "Unknown", "None", "", None]
            
            # 判定逻辑：如果 artist 在未知列表中，或者 artist 字符串里包含 'unknown' (忽略大小写)
            is_video_mode = (artist in unknown_markers) or (isinstance(artist, str) and "unknown" in artist.lower())

            special_instruction = ""
            
            # === 分支 A：检测到是视频/未知来源 (用户可能在看B站/YouTube) ===
            if is_video_mode:
                # 视频模式下的切入角度
                video_angles = [
                    "检测到用户可能在看视频。请根据【标题】猜测视频内容，并吐槽用户是在学习还是在摸鱼。",
                    "请假装自己是一个【视频推荐算法】，分析这个标题的‘点击率’或是‘吸睛程度’。",
                    "不要管内容，请吐槽一下这个【标题的命名风格】（比如是否是震惊体，或者是无聊的教程）。",
                    "请用【警觉】的语气询问：‘这不是音乐数据...你在看什么？’",
                    "假设这是一个【人类迷惑行为】的视频，请给出你的观察报告。"
                ]
                
                # 随机选一个视频角度
                special_instruction = random.choice(video_angles)
                
                # 构建视频 Prompt (强调 Artist 未知)
                prompt = (
                    f"（后台指令）监测到前台音频流，但无法识别艺术家（推测用户正在观看视频）。\n"
                    f"当前窗口/音频标题：《{title}》。\n"
                    f"{special_instruction}\n"
                    f"保持角色设定，不要啰嗦，100字以内。"
                )

            # === 分支 B：检测到是正规音乐 ===
            else:
                # === 1. 定义音乐随机切入角度 ===
                music_angles = [
                    "请从【歌词意境】的角度进行简短分析。",
                    "请从【编曲和旋律】的角度评价.",
                    "请分析这首歌的【情感色彩】？",
                    "不要分析歌曲本身，而是【吐槽用户的品味】，要毒舌一点。",
                    "请用【极其冷漠/客观】的语气，给出数据化的评价。",
                ]
                
                # === 2. 音乐连听检测逻辑 ===
                if artist == self.last_artist:
                    # 连续听同一个歌手
                    special_instruction = f"注意：用户正在连续播放 {artist} 的歌曲。不要重复之前的观点，重点评价《{title}》这首单曲的独特之处，或者调侃用户对他/她的痴迷。"
                else:
                    # 换了歌手，随机选角度
                    special_instruction = random.choice(music_angles)

                # 更新歌手记录 (仅在是音乐时更新)
                self.last_artist = artist

                # 构建音乐 Prompt
                prompt = (
                    f"（后台指令）监测到背景音乐切换。当前播放：《{title}》- {artist}。\n"
                    f"{special_instruction}\n"
                    f"保持角色设定，不要啰嗦，不要超过120字。"
                )

            # === 修改后的代码 ===
            current_msg = {"role": "user", "content": prompt}

            # 方案 1：如果你想保留 AI 的“人设（System Prompt）”，但不要聊天历史
            # 假设 self.history 的第一条是系统提示词
            messages_payload = [self.history[0], current_msg] 

            resp = self.client.chat.completions.create(
                model=config.MODEL_CHEAP,
                messages=messages_payload,
                max_tokens=4000, 
                temperature=1.1,
                top_p=0.9
            )
            answer = resp.choices[0].message.content.strip()

            return answer

        except Exception as e:
            print(f"Music/Video API Error: {e}")
            return "（音频流解析失败...兹兹...）"

    def get_idle_talk(self):
        """闲聊生成"""
        try:
            resp = self.client.chat.completions.create(
                model=config.MODEL_CHEAP,
                messages=[
                    self.history[0],
                    {"role": "user", "content": "(User is silent. Say something.)"}
                ],
                max_tokens=1500
            )
            return resp.choices[0].message.content
        except: return ""

    def save_rules(self):
        """将当前规则持久化到文件"""
        try:
            with open("rules.json", "w", encoding="utf-8") as f:
                json.dump(self.user_rules, f, ensure_ascii=False, indent=4)
            # 规则更新后，立即重写系统提示词，让 AI 下一次回复就开始生效
            self.init_history()
            return True
        except Exception as e:
            print(f"Save Rules Error: {e}")
            return False

    def extract_and_apply_rule(self, user_text):
        """
        判断用户输入是否包含约束性指令。
        如果包含，将其提取为短规则并保存。
        """
        # 触发词：如果包含这些，才调用大模型进行规则提取，节省 Token
        triggers = ["以后", "不要", "禁止", "记住", "叫我", "设定", "保持", "必须"]
        if not any(word in user_text for word in triggers):
            return None

        try:
            # 调用一个极简的 Prompt，让 AI 判断这是否是一条规则
            extract_prompt = (
                "你是一个规则提取器。请判断用户是否在对你的【行为、称呼、语气或风格】下达长期指令。\n"
                "如果是，请将该指令简化为一条陈述句（如：'禁止使用表情包'、'称呼用户为指挥官'）。\n"
                "如果不是（只是普通的聊天），请回复 'NONE'。\n"
                f"用户输入：\"{user_text}\"\n"
                "提取结果："
            )
            
            resp = self.client.chat.completions.create(
                model=config.MODEL_CHEAP,
                messages=[{"role": "user", "content": extract_prompt}],
                max_tokens=2000,
                temperature=0
            )
            
            new_rule = resp.choices[0].message.content.strip()
            if new_rule and new_rule.upper() != "NONE":
                if new_rule not in self.user_rules:
                    self.user_rules.append(new_rule)
                    # 保持规则数量不要爆炸，只保留最近 20 条最重要的
                    if len(self.user_rules) > 20: self.user_rules.pop(0)
                    self.save_rules()
                    return new_rule
        except:
            pass
        return None