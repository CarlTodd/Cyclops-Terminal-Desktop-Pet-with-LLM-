import tkinter as tk
from tkinter import ttk
import threading
import os
import time
import ctypes
from PIL import Image, ImageTk, ImageGrab
from ai_core import AICore
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


# === 1. 高 DPI 适配 ===
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    hdc = ctypes.windll.user32.GetDC(0)
    dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
    ctypes.windll.user32.ReleaseDC(0, hdc)
    SCALE = dpi / 96.0
except:
    SCALE = 1.0

class CyclopsWindow:
    def __init__(self):
        self.ai = AICore()
        self.root = tk.Tk()
        self.root.title("Cyclops Terminal")
        
        # === 状态管理 ===
        self.is_busy = False           # 全局锁：是否正在处理 AI 请求
        self.last_interact_time = time.time()
        self.last_scan_time = 0        # 用于视觉模式限流
        self.last_media_title = ""     # 用于音频模式去重
        
        # 模式控制变量 (chat / visual / audio)
        self.mode_var = tk.StringVar(value="chat") 

        # 窗口初始化
        self.init_window_geometry()
        self.setup_ui()
        self.setup_context_menu()
        self.bind_events()

        # 启动唯一的系统心跳
        self.system_heartbeat()
        self.root.mainloop()

    def init_window_geometry(self):
        self.root.attributes("-topmost", True)
        self.root.config(bg=config.TRANS_COLOR)
        try: self.root.attributes("-transparentcolor", config.TRANS_COLOR)
        except: pass

        self.win_w = int(340 * SCALE)
        self.win_h = int(580 * SCALE)
        
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        start_x = sw - self.win_w - int(20 * SCALE)
        start_y = sh - self.win_h - int(60 * SCALE)
        
        self.root.geometry(f"{self.win_w}x{self.win_h}+{start_x}+{start_y}")
        self.root.overrideredirect(True)

    def setup_ui(self):
        # 气泡区域
        self.bubble_canvas = tk.Canvas(self.root, width=int(320*SCALE), height=int(200*SCALE), 
                                       bg=config.TRANS_COLOR, highlightthickness=0)
        self.bubble_canvas.pack(pady=(int(10*SCALE), 0))
        self.draw_bubble_bg(int(160*SCALE)) # 初始背景

        self.out_frame = tk.Frame(self.bubble_canvas, bg="#FDF6E3")
        self.bubble_window = self.bubble_canvas.create_window(
            int(160*SCALE), int(85*SCALE), window=self.out_frame, 
            width=int(260*SCALE), height=int(120*SCALE)
        )
        
        font_size = max(10, int(11)) # 字体本身不需要完全跟随 SCALE，操作系统会缩放
        self.msg_text = tk.Text(self.out_frame, bg="#FDF6E3", fg="#2D3436", 
                                font=("Microsoft YaHei UI", font_size),
                                bd=0, highlightthickness=0, wrap="word", state="disabled",
                                spacing2=int(4*SCALE))
        self.msg_text.pack(expand=True, fill="both")
        
        self.update_output("(准备就绪)\nName's Cyclops. Definitely the good guy.")

        # 立绘
        self.load_character_image()
        self.img_label = tk.Label(self.root, image=self.photo, bg=config.TRANS_COLOR, bd=0)
        self.img_label.pack(pady=int(5*SCALE))

        # === 输入区域 (修改版) ===
        self.placeholder = "To me, My X-Men!"
        self.input_canvas = tk.Canvas(self.root, width=int(320*SCALE), height=int(60*SCALE), 
                                       bg=config.TRANS_COLOR, highlightthickness=0)
        self.input_canvas.pack(pady=int(5*SCALE))
        self.draw_rounded_rect(self.input_canvas, int(10*SCALE), int(5*SCALE), int(270*SCALE), int(50*SCALE), 
                               int(20*SCALE), fill="white", outline="#DCDDE1", width=2)
        
        self.in_frame = tk.Frame(self.input_canvas, bg="white")
        self.input_canvas.create_window(int(135*SCALE), int(28*SCALE), window=self.in_frame, 
                                        width=int(220*SCALE), height=int(30*SCALE))
        
        # === 关键修改 ===
        # 1. 字体大小用负数 (-14)，解决拼音框过小问题
        input_font_size = -int(14 * SCALE)
        
        # 2. wrap="word"：启用自动换行
        self.input_entry = tk.Text(self.in_frame, font=("Microsoft YaHei UI", input_font_size), 
                                   bd=0, bg="white", 
                                   wrap="word",   # <--- 这里改成了 word
                                   height=1,      # <--- 保持高度为 1 行
                                   fg="gray")
        
        self.input_entry.insert("1.0", self.placeholder)
        self.input_entry.pack(fill="both")

        # 3. 绑定事件：打字时光标自动跟随、鼠标滚轮竖向滚动
        self.input_entry.bind("<KeyRelease>", self._auto_scroll_caret)
        self.input_entry.bind("<MouseWheel>", self._on_input_mousewheel)

        # 截图按钮
        self.scan_btn = tk.Button(self.input_canvas, text="S", font=("Microsoft YaHei UI", int(6*SCALE)), 
                                  bg="#FDF6E3", fg="#E84118", bd=0, cursor="hand2", command=self.manual_snapshot)
        self.input_canvas.create_window(int(290*SCALE), int(28*SCALE), window=self.scan_btn, width=int(35*SCALE), height=int(35*SCALE))

    def setup_context_menu(self):
        self.context_menu = tk.Menu(self.root, tearoff=0)
        
        # 模式选择部分 (Radiobutton 实现互斥)
        self.context_menu.add_radiobutton(label="💬 普通对话模式", variable=self.mode_var, value="chat", command=self.on_mode_change)
        self.context_menu.add_radiobutton(label="👓 视觉监控模式", variable=self.mode_var, value="visual", command=self.on_mode_change)
        self.context_menu.add_radiobutton(label="🎵 音频识别模式", variable=self.mode_var, value="audio", command=self.on_mode_change)
        
        self.context_menu.add_separator()
        # 2. 语言选择 (新加)
        self.lang_var = tk.StringVar(value="CN") # 默认为中文
        lang_menu = tk.Menu(self.context_menu, tearoff=0)
        lang_menu.add_radiobutton(label="🇨🇳 中文模式", variable=self.lang_var, value="CN", 
                                  command=lambda: self.change_language("CN"))
        lang_menu.add_radiobutton(label="🇺🇸 English Mode", variable=self.lang_var, value="EN", 
                                  command=lambda: self.change_language("EN"))
        self.context_menu.add_cascade(label="🌐 语言切换 / Language", menu=lang_menu)

        self.context_menu.add_separator()
        self.context_menu.add_command(label="📜 查看对话历史", command=self.show_history_window)
        self.context_menu.add_command(label="🐕 调整行为准则", command=self.show_rules_window)
        self.context_menu.add_command(label="清空记忆", command=self.reset_memory_ui)
        self.context_menu.add_command(label="退出系统", command=self.root.destroy)

    def change_language(self, lang_code):
        """处理语言切换的 UI 反馈"""
        self.ai.switch_language(lang_code)
        
        if lang_code == "CN":
            msg = "【系统】人设语言已切换为：中文。"
        else:
            msg = "【System】Personality language switched to: English."
            
        self.update_output(msg)

    def on_mode_change(self):
        """当用户在右键菜单切换模式时触发"""
        mode = self.mode_var.get()
        mapping = {"chat": "普通对话", "visual": "屏幕视觉监控", "audio": "音频流分析"}
        self.update_output(f"【系统】切换至：{mapping.get(mode, mode)}模式。")
        # 切换模式时重置相关计数器
        self.last_media_title = "" 
        self.last_scan_time = time.time() # 避免切换瞬间立刻触发扫描

    # === 核心心跳逻辑 (Unified Loop) ===
    def system_heartbeat(self):
        """每隔一段时间检查一次状态，根据模式分发任务"""
        
        # 如果 AI 正在忙，或者用户正在输入（焦点在输入框），跳过本次自动检测
        if self.is_busy:
            self.root.after(1000, self.system_heartbeat)
            return

        current_mode = self.mode_var.get()
        now = time.time()

        # 1. 视觉监控模式逻辑
        if current_mode == "visual":
            # 限制频率：每 600 秒自动看一次，或者刚切换时
            if now - self.last_scan_time > 600:
                self.last_scan_time = now
                self.execute_visual_scan(is_auto=True)

        # 2. 音频识别模式逻辑
        elif current_mode == "audio":
            # 频率：每 20 秒检查一次系统媒体
            self.check_music_status()

        # 3. 闲聊逻辑 (只在聊天模式下有，防止冲突，优先度最低)
        elif now - self.last_interact_time > 600: # 10分钟无操作(错开视觉监控)
                self.last_interact_time = now
                self.trigger_idle_talk()
            

        # 下一次心跳：20秒后 (平衡响应速度和性能)
        self.root.after(20000, self.system_heartbeat)

    # === 各模式具体任务 ===

    def check_music_status(self):
        """音频模式的具体任务"""
        def task():
            media = self.ai.get_current_media_info()
            if media and media['title'] != self.last_media_title:
                self.is_busy = True
                self.last_media_title = media['title']
                
                title = media['title']
                artist = media['artist']
                
                # UI 反馈
                self.update_output(f"监测到音轨切换：\n《{title}》- {artist}\n正在分析...")
                
                # AI 生成评价
                comment = self.ai.comment_on_music(title, artist)
                # === 新增：将音频评价存入历史 ===
                history_msg = f"系统检测到正在播放：{title} - {artist}。你的评价是：{comment}"
                self.ai.history.append({"role": "assistant", "content": history_msg})
                # ============================
                self.update_output(f"【正在播放】\n《{title}》\n{comment}")
                self.is_busy = False
        
        threading.Thread(target=task, daemon=True).start()

    def execute_visual_scan(self, is_auto=False):
        """视觉模式的具体任务"""
        self.is_busy = True
        if not is_auto:
            self.root.withdraw() # 手动截图时隐藏窗口
            time.sleep(0.3)
            self.update_output("（监控）正在扫描屏幕...")
        else:
            self.update_output("（自动监控）正在扫描屏幕...")

        try:
            screenshot = ImageGrab.grab()
            if not is_auto: self.root.deiconify()
            
            temp_file = os.path.abspath("scan_cache.png")
            screenshot.save(temp_file)
            
            def task():
                 # === 修改开始：获取最近的对话摘要 ===
                # 从 self.ai.history 获取最后 2 组对话 (假设结构是 list)
                # 这是一个简单的拼接，让视觉 AI 知道一点上下文
                recent_context = ""
                if len(self.ai.history) > 0:
                    # 简单过滤掉太长的系统指令，只取最近的
                    recent_msgs = self.ai.history[-2:] 
                    for msg in recent_msgs:
                        role = "我" if msg['role'] == 'user' else "你"
                        content = msg['content'][:50] # 截断一下防止太长
                        recent_context += f"{role}: {content}\n"

                # 构建带记忆的 Prompt
                base_prompt = "简要评价用户当前行为," if is_auto else "分析当前屏幕内容。"
                prompt = f"这是我们刚才的对话片段：\n{recent_context}\n现在，请结合屏幕截图，{base_prompt}"
                
                # === 修改结束 ===
                res = self.ai.analyze_image(temp_file, prompt)
                # === 新增：将视觉分析存入历史 ===
                self.ai.history.append({"role": "user", "content": "[系统自动截屏分析请求]"})
                self.ai.history.append({"role": "assistant", "content": res})
                # ============================
                
                self.update_output(res)
                if os.path.exists(temp_file): os.remove(temp_file)
                self.is_busy = False
                self.last_interact_time = time.time()

            threading.Thread(target=task, daemon=True).start()
        except Exception as e:
            self.update_output(f"截图失败: {e}")
            self.root.deiconify()
            self.is_busy = False

    def trigger_idle_talk(self):
        self.is_busy = True
        def task():
            msg = self.ai.get_idle_talk()
            if msg: self.update_output(msg)
            self.is_busy = False
        threading.Thread(target=task, daemon=True).start()

    # === 用户交互处理 ===

    def handle_input_return(self, event):
        if event.state & 0x0001: return 
        self.send_message_thread()
        return "break"

    def send_message_thread(self):
        """手动发送消息，优先级最高"""
        query = self.input_entry.get("1.0", "end-1c").strip()
        if not query or query == self.placeholder: return
        
        self.is_busy = True
        self.input_entry.delete("1.0", tk.END)
        self.last_interact_time = time.time()
        self.update_output("正在思考...")
        
        def task():
            ans, status = self.ai.chat(query)
            if status == "shutdown":
                # 致命错误：红色文字，然后关机
                self.root.after(0, lambda: self.shake_window(duration=600, intensity=7))
                self.update_output(f"❌ （即将关闭窗口）\n{ans}")
                self.root.after(0, lambda: self.trigger_shutdown_sequence(ans))
                return # 线程结束，不需要重置 is_busy
            self.update_output(ans)
            self.is_busy = False
            
        threading.Thread(target=task, daemon=True).start()

    def manual_snapshot(self):
        """手动点击 S 按钮"""
        self.execute_visual_scan(is_auto=False)

    def reset_memory_ui(self):
        self.ai.reset_memory()
        self.update_output("记忆核心已重置。")

    # === UI 辅助绘图与事件 (保持原有逻辑) ===
    
    def update_output(self, text):
        """线程安全的 UI 更新 (打字机效果 + 高度预计算)"""
        def _inner():
            # === 0. 如果有正在进行的打字任务，先取消 ===
            # 防止上一句话还没说完，下一句话就叠加上去了
            if hasattr(self, '_typing_task') and self._typing_task:
                self.root.after_cancel(self._typing_task)
                self._typing_task = None

            # === 1. 预计算阶段 (Pre-calculation) ===
            # 先将完整文本放入，为了计算最终需要的高度，避免窗口在打字时忽大忽小
            self.msg_text.config(state="normal")
            self.msg_text.delete("1.0", tk.END)
            self.msg_text.insert(tk.END, text)
            
            # 强制刷新布局以获取准确行数
            self.msg_text.update_idletasks()
            
            # 使用 displaylines 获取视觉行数
            count = self.msg_text.count("1.0", "end", "displaylines")
            line_count = count[0] if count else 1
            line_count += 0.5 # padding
            
            # 计算高度参数
            row_h = int(22 * SCALE) 
            new_text_h = max(int(80*SCALE), min(int(400*SCALE), int(line_count * row_h)))
            new_bubble_h = new_text_h + int(40*SCALE)
            
            # === 2. 调整窗口与气泡几何形状 (一次性定型) ===
            self.bubble_canvas.config(height=new_bubble_h + int(20*SCALE))
            self.bubble_canvas.itemconfig(self.bubble_window, height=new_text_h)
            self.bubble_canvas.coords(self.bubble_window, int(160*SCALE), new_bubble_h/2)
            self.draw_bubble_bg(new_bubble_h)
            
            # 窗口整体高度自适应 (保持底部固定，向上生长)
            total_win_h = new_bubble_h + int(400*SCALE)
            geom = self.root.geometry().split('+')
            current_y = int(geom[2])
            current_h = self.root.winfo_height()
            new_y = current_y - (total_win_h - current_h)
            self.root.geometry(f"{self.win_w}x{total_win_h}+{geom[1]}+{new_y}")

            # === 3. 准备打字机动画 ===
            # 高度定好了，现在把文字清空，准备逐字画出来
            self.msg_text.delete("1.0", tk.END)
            self.msg_text.config(state="disabled")
            
            # 启动递归打字函数
            _type_loop(0)

        def _type_loop(index):
            # 递归结束条件：字打完了
            if index >= len(text):
                self._typing_task = None
                return
            
            self.msg_text.config(state="normal")
            char = text[index]
            self.msg_text.insert(tk.END, char)
            self.msg_text.see(tk.END) # 始终滚动到最底端
            self.msg_text.config(state="disabled")
            
            # === 4. 动态语速控制 ===
            # 基础速度：每个字 30ms
            delay = 30 
            # 遇到标点符号，停顿久一点，更有“说话”的感觉
            if char in "，。！？：\n,.!?:":
                delay = 150 
            
            # 安排下一个字的显示
            self._typing_task = self.root.after(delay, lambda: _type_loop(index + 1))

        # 在主线程执行
        self.root.after(0, _inner)

    def draw_bubble_bg(self, rect_h):
        self.bubble_canvas.delete("bg")
        w = int(310 * SCALE)
        self.draw_rounded_rect(self.bubble_canvas, int(10*SCALE), int(10*SCALE), w, rect_h, int(40*SCALE), 
                               fill="#FDF6E3", outline="#E6DCC3", width=3, tags="bg")
        # 气泡小尾巴
        self.bubble_canvas.create_polygon([int(150*SCALE), rect_h, int(170*SCALE), rect_h, int(160*SCALE), rect_h+int(15*SCALE)], 
                                          fill="#FDF6E3", outline="#E6DCC3", width=2, tags="bg")
        self.bubble_canvas.tag_lower("bg")

    def draw_rounded_rect(self, canvas, x1, y1, x2, y2, radius, **kwargs):
        points = [x1+radius, y1, x1+radius, y1, x2-radius, y1, x2-radius, y1, x2, y1, x2, y1+radius, x2, y1+radius, x2, y2-radius, x2, y2-radius, x2, y2, x2-radius, y2, x2-radius, y2, x1+radius, y2, x1+radius, y2, x1, y2, x1, y2-radius, x1, y2-radius, x1, y1+radius, x1, y1+radius, x1, y1]
        return canvas.create_polygon(points, **kwargs, smooth=True)

    def load_character_image(self):
        try:
            size = int(200 * SCALE)
            if os.path.exists(config.IMAGE_FILENAME):
                img_path = local_path(config.IMAGE_FILENAME)
                img = Image.open(img_path).convert("RGBA")
                img = img.resize((size, size), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(img)
            else: 
                # 红色占位符
                self.photo = ImageTk.PhotoImage(Image.new('RGBA', (size, size), (200, 50, 50, 255)))
        except: pass

    def bind_events(self):
        # 拖拽
        for w in [self.bubble_canvas, self.img_label, self.input_canvas]:
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)
        # 右键菜单
        self.img_label.bind("<Button-3>", lambda e: self.context_menu.post(e.x_root, e.y_root))
        
        # 输入框占位符处理
        self.input_entry.bind("<FocusIn>", self._clear_placeholder)
        self.input_entry.bind("<FocusOut>", self._add_placeholder)
        self.input_entry.bind("<Return>", self.handle_input_return)

    def start_drag(self, e):
        self.offset_x, self.offset_y = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()
    def do_drag(self, e):
        self.root.geometry(f"+{e.x_root - self.offset_x}+{e.y_root - self.offset_y}")
    
    def _clear_placeholder(self, event):
        if self.input_entry.get("1.0", "end-1c") == self.placeholder:
            self.input_entry.delete("1.0", tk.END)
            self.input_entry.config(fg="#2D3436")

    def _add_placeholder(self, event):
        if not self.input_entry.get("1.0", "end-1c").strip():
            self.input_entry.insert("1.0", self.placeholder)
            self.input_entry.config(fg="gray")
            
    def _auto_scroll_caret(self, event=None):
        """用户打字时，确保光标始终在视野内"""
        self.input_entry.see(tk.INSERT)

    def _on_input_mousewheel(self, event):
        """鼠标滚轮事件：控制输入框竖向滚动"""
        # yview_scroll 控制垂直滚动
        # 负号是为了修正方向（滚轮向下滚，内容向上走）
        self.input_entry.yview_scroll(int(-1*(event.delta/120)), "units")
        return "break" # 阻止默认事件传递
    
    def show_history_window(self):
        """创建一个独立的弹窗来显示最近的对话历史"""
        # 1. 创建顶层窗口
        history_win = tk.Toplevel(self.root)
        history_win.title("对话记录存档")
        history_win.attributes("-topmost", True)  # 保持在最前
        
        # 设置窗口大小 (根据 SCALE 缩放)
        w, h = int(400 * SCALE), int(500 * SCALE)
        history_win.geometry(f"{w}x{h}")
        history_win.configure(bg="#FDF6E3") # 延续你的米色背景

        # 2. 标题标签
        title_label = tk.Label(history_win, text="—— 核心记忆存根 ——", 
                               font=("Microsoft YaHei UI", int(12 * SCALE), "bold"),
                               bg="#FDF6E3", fg="#2D3436", pady=int(10*SCALE))
        title_label.pack()

        # 3. 带滚动条的文本区域
        text_frame = tk.Frame(history_win, bg="#FDF6E3")
        text_frame.pack(expand=True, fill="both", padx=10, pady=10)

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        # 字体大小用负数保证高 DPI 下显示正常
        h_font_size = -int(12 * SCALE)
        history_text = tk.Text(text_frame, bg="white", fg="#2D3436",
                               font=("Microsoft YaHei UI", h_font_size),
                               wrap="word", bd=0, padx=10, pady=10,
                               yscrollcommand=scrollbar.set)
        history_text.pack(side="left", expand=True, fill="both")
        scrollbar.config(command=history_text.yview)

        # 4. 插入数据
        # 提取最近的 20 条消息 (10轮对话 = 10条用户 + 10条AI)
        # 排除掉第一条系统提示词 (index 0)
        full_history = self.ai.history[1:] if len(self.ai.history) > 1 else []
        recent_history = full_history[-20:] if full_history else []

        if not recent_history:
            history_text.insert(tk.END, "\n\n[ 记忆库目前为空 ]")
            history_text.tag_add("center", "1.0", tk.END)
            history_text.tag_config("center", justify="center")
        else:
            # 定义颜色标签
            history_text.tag_config("user_tag", foreground="#E84118", font=("Microsoft YaHei UI", h_font_size, "bold"))
            history_text.tag_config("ai_tag", foreground="#2F3640", font=("Microsoft YaHei UI", h_font_size, "bold"))
            history_text.tag_config("time_tag", foreground="gray", font=("Microsoft YaHei UI", -int(10*SCALE)))

            for msg in recent_history:
                role = msg.get("role", "")
                content = msg.get("content", "")

                if role == "user":
                    history_text.insert(tk.END, "● 我:\n", "user_tag")
                else:
                    history_text.insert(tk.END, "○ Cyclops:\n", "ai_tag")
                
                history_text.insert(tk.END, f"{content}\n\n")

        # 设置为只读
        history_text.config(state="disabled")
        # 自动滚动到底部
        history_text.see(tk.END)

    def show_rules_window(self):
        """弹窗显示并允许删除当前的长期规则"""
        rules_win = tk.Toplevel(self.root)
        rules_win.title("行为准则管理器")
        rules_win.geometry(f"{int(300*SCALE)}x{int(400*SCALE)}")
        rules_win.attributes("-topmost", True)
        rules_win.configure(bg="#FDF6E3")

        tk.Label(rules_win, text="AI 当前遵循的规则:", bg="#FDF6E3", font=("Arial", 10, "bold")).pack(pady=10)

        listbox = tk.Listbox(rules_win, bg="white", font=("Arial", 9), bd=0)
        listbox.pack(expand=True, fill="both", padx=10, pady=5)

        for r in self.ai.user_rules:
            listbox.insert(tk.END, f"• {r}")

        def delete_rule():
            sel = listbox.curselection()
            if sel:
                idx = sel[0]
                rule_text = self.ai.user_rules.pop(idx)
                self.ai.save_rules() # 保存并刷新 history
                listbox.delete(idx)
                self.update_output(f"已移除规则: {rule_text}")

        btn_del = tk.Button(rules_win, text="删除选中规则", command=delete_rule, bg="#E84118", fg="white", bd=0)
        btn_del.pack(pady=10)
    
    def shake_window(self, duration=500, intensity=5):
        """
        窗口震动效果
        duration: 震动持续时间(ms)
        intensity: 震动幅度(像素)
        """
        # 获取当前窗口位置
        geom = self.root.geometry().split('+')
        orig_x, orig_y = int(geom[1]), int(geom[2])
        
        def _do_shake(remaining):
            if remaining <= 0:
                # 震动结束，回归原位
                self.root.geometry(f"+{orig_x}+{orig_y}")
                return
            
            # 随机偏移
            dx = random.randint(-intensity, intensity)
            dy = random.randint(-intensity, intensity)
            self.root.geometry(f"+{orig_x + dx}+{orig_y + dy}")
            
            # 30ms 后进行下一次震动
            self.root.after(30, lambda: _do_shake(remaining - 30))
        
        _do_shake(duration)

    def trigger_shutdown_sequence(self, message):
        """致命错误：显示最后消息并进入倒计时关机"""
        # 1. 禁用输入，防止用户挣扎
        self.input_entry.config(state="disabled")
        self.scan_btn.config(state="disabled")
        
        # 2. 先打印 AI 的最后通牒
        
        # 3. 震动一下，表示系统崩溃
        self.shake_window(duration=1000, intensity=10)

        def _countdown(count):
            if count <= 0:
                self.root.destroy()
                return
            
            # 在 Text 组件末尾追加倒计时文字
            self.msg_text.config(state="normal")
            self.msg_text.insert(tk.END, f"\n\n[ 核心链路切断中... {count}s ]", "warning_red")
            self.msg_text.tag_config("warning_red", foreground="red", font=("Microsoft YaHei UI", int(10*SCALE), "bold"))
            self.msg_text.config(state="disabled")
            self.msg_text.see(tk.END)
            
            self.root.after(1000, lambda: _countdown(count - 1))

        # 预留一点时间让 AI 把话说完再开始倒计时
        self.root.after(2000, lambda: _countdown(5))
