"""
PalFastExpeditions - 帕鲁远征自动化工具
使用 OpenCV + Tesseract OCR + PyAutoGUI 实现屏幕文字识别与自动点击
"""

import ctypes
import ctypes.wintypes
import json
import threading
import time
import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

import cv2
import numpy as np
import pyautogui
import pytesseract
from pynput import keyboard
from PIL import ImageGrab

# ============================================================
# 全局配置
# ============================================================

VERSION = "v0.1-beta"

# Tesseract 路径 (自动检测，找不到则用默认路径)
def _find_tesseract():
    """自动查找 tesseract.exe"""
    import shutil
    # 1. 环境变量 PATH
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"D:\Program Files\Tesseract-OCR\tesseract.exe",
        r"D:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return "tesseract"  # 兜底，让 pytesseract 报错提示

pytesseract.pytesseract.tesseract_cmd = _find_tesseract()

# OCR 语言 (中文简体 + 英文)
OCR_LANG = "chi_sim+eng"

# 触发热键 (默认 PageDown，可自定义)
HOTKEY = keyboard.Key.page_down
_hotkey_binding = False  # True 时下一个按键将被设为热键

# 热键显示名称映射
_KEY_DISPLAY = {
    'page_down': 'PageDown', 'page_up': 'PageUp',
    'f1': 'F1', 'f2': 'F2', 'f3': 'F3', 'f4': 'F4',
    'f5': 'F5', 'f6': 'F6', 'f7': 'F7', 'f8': 'F8',
    'f9': 'F9', 'f10': 'F10', 'f11': 'F11', 'f12': 'F12',
    'home': 'Home', 'end': 'End',
    'insert': 'Insert', 'delete': 'Delete',
    'space': 'Space', 'tab': 'Tab',
    'enter': 'Enter', 'esc': 'Esc',
    'up': '↑', 'down': '↓', 'left': '←', 'right': '→',
}


def _key_to_display(key):
    """pynput 按键 → 显示名称"""
    if key is None:
        return "无"
    if isinstance(key, keyboard.Key):
        return _KEY_DISPLAY.get(key.name, key.name)
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char.upper()
    return str(key)


def _parse_hotkey(s):
    """配置字符串 → pynput 按键"""
    if s is None:
        return None
    key = getattr(keyboard.Key, s, None)
    if key is not None:
        return key
    if len(s) == 1:
        return keyboard.KeyCode.from_char(s.lower())
    return None


def _hotkey_to_config(key):
    """pynput 按键 → 配置字符串"""
    if key is None:
        return None
    if isinstance(key, keyboard.Key):
        return key.name
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char.lower()
    return None

# 截图保存目录 (调试用)
SCREENSHOT_DIR = "screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# PyAutoGUI 安全设置
pyautogui.FAILSAFE = True  # 鼠标移到左上角可紧急停止
pyautogui.PAUSE = 0.1      # 每个操作之间的间隔

# ============================================================
# 延迟配置系统
# ============================================================

def _resolve_config_dir():
    """配置目录：优先用户文档目录（打包后），开发环境则存到脚本目录下的 config"""
    # 打包后 (PyInstaller) → 优先文档目录，保证配置持久化
    if getattr(sys, 'frozen', False):
        docs = os.path.join(os.path.expanduser("~"), "Documents", "PalFastExpeditions", "config")
        try:
            os.makedirs(docs, exist_ok=True)
            return docs
        except OSError:
            pass
        # 文档目录不可写，尝试 exe 同目录
        exe_dir = os.path.join(os.path.dirname(sys.executable), "config")
        os.makedirs(exe_dir, exist_ok=True)
        return exe_dir

    # 开发环境 → 脚本目录下的 config
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
    if os.path.isdir(local):
        return local
    try:
        os.makedirs(local, exist_ok=True)
        test_file = os.path.join(local, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return local
    except OSError:
        pass
    # 脚本目录不可写，回退到文档目录
    docs = os.path.join(os.path.expanduser("~"), "Documents", "PalFastExpeditions", "config")
    os.makedirs(docs, exist_ok=True)
    print(f"[配置] 脚本目录不可写，配置保存到: {docs}")
    return docs

CONFIG_DIR = _resolve_config_dir()
DELAYS_PATH = os.path.join(CONFIG_DIR, "delays.json")

# 默认延迟参数（秒）
DEFAULT_DELAYS = {
    "pre_action":       0.3,   # 操作前等待（按F键、回拨时间等）
    "post_screenshot":  0.5,   # 截图后等待
    "detection_retry":  1.0,   # 检测失败重试等待
    "scroll_wait":      0.5,   # 翻页后等待
    "click_move":       0.2,   # 鼠标移动耗时
    "post_click":       0.5,   # 点击后等待
    "step7_dispatch_wait": 1.0,  # 步骤7等待派遣界面
    "step10_pre_f":     0.8,   # 步骤10按F前等待
    "step12_detect_wait": 1.0,  # 步骤12检测物品栏前等待
    "step12_reward_wait": 1.0,  # 步骤12取奖励后等待
    "step12_close_wait": 0.5,   # 步骤12关闭菜单后等待
    "time_restore_wait": 0.5,   # 恢复时间后等待
}

# 延迟参数中文说明
DELAY_LABELS = {
    "pre_action":       "操作前等待",
    "post_screenshot":  "截图后等待",
    "detection_retry":  "检测重试等待",
    "scroll_wait":      "翻页后等待",
    "click_move":       "鼠标移动耗时",
    "post_click":       "点击后等待",
    "step7_dispatch_wait": "派遣界面等待",
    "step10_pre_f":     "开箱前等待",
    "step12_detect_wait": "物品栏检测等待",
    "step12_reward_wait": "取奖励后等待",
    "step12_close_wait": "关闭菜单后等待",
    "time_restore_wait": "恢复时间后等待",
}

# 当前延迟值（运行时使用）
DELAYS = dict(DEFAULT_DELAYS)


def load_delays_config():
    """从 config/delays.json 加载延迟配置和热键"""
    global DELAYS, HOTKEY
    if os.path.exists(DELAYS_PATH):
        try:
            with open(DELAYS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "delays" in data:
                for k, v in data["delays"].items():
                    if k in DELAYS:
                        DELAYS[k] = float(v)
                print(f"[配置] 已加载延迟配置: {DELAYS_PATH}")
            if "hotkey" in data:
                hk = _parse_hotkey(data["hotkey"])
                if hk is not None or data["hotkey"] is None:
                    HOTKEY = hk
                print(f"[配置] 已加载热键: {_key_to_display(HOTKEY)}")
        except Exception as e:
            print(f"[配置] 加载配置失败: {e}，使用默认值")


def save_delays_config():
    """保存延迟配置和热键到 config/delays.json"""
    try:
        with open(DELAYS_PATH, "w", encoding="utf-8") as f:
            json.dump({"delays": DELAYS, "hotkey": _hotkey_to_config(HOTKEY)},
                      f, ensure_ascii=False, indent=4)
        log(f"配置已保存: {DELAYS_PATH}")
    except Exception as e:
        log(f"保存配置失败: {e}")


# 启动时加载配置
load_delays_config()

class SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", ctypes.wintypes.WORD),
        ("wMonth", ctypes.wintypes.WORD),
        ("wDayOfWeek", ctypes.wintypes.WORD),
        ("wDay", ctypes.wintypes.WORD),
        ("wHour", ctypes.wintypes.WORD),
        ("wMinute", ctypes.wintypes.WORD),
        ("wSecond", ctypes.wintypes.WORD),
        ("wMilliseconds", ctypes.wintypes.WORD),
    ]


def get_system_time() -> SYSTEMTIME:
    st = SYSTEMTIME()
    ctypes.windll.kernel32.GetLocalTime(ctypes.byref(st))
    return st


def set_system_time(st: SYSTEMTIME) -> bool:
    return bool(ctypes.windll.kernel32.SetLocalTime(ctypes.byref(st)))


def system_time_to_seconds(st: SYSTEMTIME) -> int:
    return st.wHour * 3600 + st.wMinute * 60 + st.wSecond


def adjust_time(st: SYSTEMTIME, offset_seconds: float = 0, offset_ms: int = 0) -> SYSTEMTIME:
    """调整时间，支持跨天/跨月/跨年，返回新的 SYSTEMTIME"""
    dt = datetime(st.wYear, st.wMonth, st.wDay,
                 st.wHour, st.wMinute, st.wSecond,
                 st.wMilliseconds * 1000)  # datetime 微秒
    delta_ms = int(offset_seconds * 1000) + offset_ms
    dt = dt + __import__('datetime').timedelta(milliseconds=delta_ms)

    new_st = SYSTEMTIME()
    new_st.wYear = dt.year
    new_st.wMonth = dt.month
    new_st.wDayOfWeek = dt.weekday()  # Python: 0=Monday, Windows: 0=Sunday
    new_st.wDay = dt.day
    new_st.wHour = dt.hour
    new_st.wMinute = dt.minute
    new_st.wSecond = dt.second
    new_st.wMilliseconds = dt.microsecond // 1000
    return new_st


def format_time(st: SYSTEMTIME) -> str:
    return f"{st.wYear}/{st.wMonth:02d}/{st.wDay:02d} {st.wHour:02d}:{st.wMinute:02d}:{st.wSecond:02d}"


def rollback_time_one_hour():
    """回拨系统时间1小时，等待200ms后不恢复（由调用方控制恢复时机）"""
    original = get_system_time()
    log(f"当前系统时间: {format_time(original)}")

    shifted = adjust_time(original, -3600)
    if set_system_time(shifted):
        log(f"已回拨至: {format_time(shifted)}")
        return original  # 返回原始时间以便后续恢复
    else:
        log("回拨时间失败！请确保以管理员权限运行")
        return None


def restore_time(original: SYSTEMTIME):
    """恢复系统时间（补偿经过的时间不在此处处理，因为流程中后续会自动恢复）"""
    if set_system_time(original):
        log(f"已恢复至: {format_time(original)}")
    else:
        log("恢复时间失败！请手动调整")


# ============================================================
# 日志
# ============================================================

_log_callback = None  # UI 日志回调


def log(msg: str):
    """打印日志并可选推送到 UI"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    print(line)
    if _log_callback:
        _log_callback(line)


# ============================================================
# OCR 工具函数
# ============================================================

def take_screenshot() -> np.ndarray:
    """截取全屏，返回 OpenCV 格式的图像 (BGR)"""
    screenshot = ImageGrab.grab()
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    return img


def save_debug_screenshot(img: np.ndarray, name: str):
    """保存截图用于调试"""
    path = os.path.join(SCREENSHOT_DIR, f"{name}_{int(time.time()*1000)}.png")
    cv2.imwrite(path, img)
    return path


def _preprocess_for_ocr(img: np.ndarray):
    """OCR 预处理：灰度 → 放大3倍 → 反转（游戏深色背景白字）"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 放大 3 倍，Tesseract 对小字体中文需要放大才准
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # 反转：游戏深色背景 → 白底黑字，符合 Tesseract 期望
    inverted = cv2.bitwise_not(gray)
    return inverted


def find_text_position(img: np.ndarray, target_text: str):
    """
    在图像中查找目标文字的位置
    返回: (x, y, w, h) 屏幕坐标，如果未找到返回 None
    """
    scale = 3  # 与 _preprocess_for_ocr 中的放大倍数一致
    processed = _preprocess_for_ocr(img)
    # --psm 11: 稀疏文本模式，最适合游戏 UI 中散布的文字
    data = pytesseract.image_to_data(processed, lang=OCR_LANG, output_type=pytesseract.Output.DICT, config="--psm 11")

    # 收集所有有效词
    all_words = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        conf = int(data["conf"][i])
        if conf < 20 or not text:
            continue
        all_words.append({
            "text": text,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
            "conf": conf,
        })
        # 单词精确匹配
        if target_text in text:
            x, y, w, h = data["left"][i] // scale, data["top"][i] // scale, data["width"][i] // scale, data["height"][i] // scale
            log(f"找到文字 '{text}' (置信度: {conf}) 位置: ({x}, {y}, {w}, {h})")
            return (x, y, w, h)

    # 第二步：同行内按左右位置排序后拼接相邻词（中文 OCR 经常拆词且顺序错乱）
    # 先按 top 分行（top 差值 < 20 视为同行），同行内按 left 排序
    ROW_THRESHOLD = 20
    all_words.sort(key=lambda w: (w["top"], w["left"]))
    rows = []
    for w in all_words:
        if not rows or abs(w["top"] - rows[-1][0]["top"]) > ROW_THRESHOLD:
            rows.append([w])
        else:
            rows[-1].append(w)
    for row in rows:
        row.sort(key=lambda w: w["left"])

    # 在每行内拼接相邻词
    for row in rows:
        for start in range(len(row)):
            combined = ""
            for end in range(start, min(start + 12, len(row))):
                combined += row[end]["text"]
                if target_text in combined:
                    # 找目标文字第一个字符出现在哪个词中
                    actual_start = start
                    char_pos = 0
                    for k in range(start, end + 1):
                        next_pos = char_pos + len(row[k]["text"])
                        if next_pos > combined.index(target_text):
                            actual_start = k
                            break
                        char_pos = next_pos
                    words_range = row[actual_start:end + 1]
                    x = words_range[0]["left"] // scale
                    y = min(w["top"] for w in words_range) // scale
                    x2 = max(w["left"] + w["width"] for w in words_range) // scale
                    y2 = max(w["top"] + w["height"] for w in words_range) // scale
                    log(f"找到拼接文字 '{combined}' 位置: ({x}, {y}, {x2 - x}, {y2 - y})")
                    return (x, y, x2 - x, y2 - y)

    return None


def _fuzzy_match_chinese(target: str, text: str, min_ratio: float = 0.6) -> bool:
    """模糊匹配中文：
    1. 精确子串匹配
    2. 目标前缀匹配（取目标前60%的字看是否出现在文本中）
    3. 字符重叠率匹配（共同字符数/目标字符数 >= min_ratio）
    """
    # 精确子串
    if target in text:
        return True
    # 前缀匹配：取前 max(2, 60%) 个字，要求出现在文本开头（防止 "ie世界树地下" 误匹配）
    prefix_len = max(2, int(len(target) * 0.6))
    prefix = target[:prefix_len]
    if text.startswith(prefix):
        return True
    # 字符重叠率
    target_chars = set(target)
    text_chars = set(text)
    overlap = len(target_chars & text_chars)
    if len(target_chars) > 0 and overlap / len(target_chars) >= min_ratio:
        return True
    return False


def find_text_fuzzy_position(img: np.ndarray, target_text: str):
    """模糊查找文字位置（容忍OCR错字）。返回 (x, y, w, h) 或 None"""
    scale = 3
    processed = _preprocess_for_ocr(img)
    data = pytesseract.image_to_data(processed, lang=OCR_LANG,
                                     output_type=pytesseract.Output.DICT, config="--psm 11")

    all_words = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        conf = int(data["conf"][i])
        if conf < 10 or not text:
            continue
        all_words.append({
            "text": text,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
            "conf": conf,
        })
        if _fuzzy_match_chinese(target_text, text):
            x, y, w, h = data["left"][i] // scale, data["top"][i] // scale, data["width"][i] // scale, data["height"][i] // scale
            log(f"模糊匹配找到 '{text}' (conf:{conf}) 位置: ({x},{y},{w},{h})")
            return (x, y, w, h)

    # 同行拼接后模糊匹配
    ROW_THRESHOLD = 20
    all_words.sort(key=lambda w: (w["top"], w["left"]))
    rows = []
    for w in all_words:
        if not rows or abs(w["top"] - rows[-1][0]["top"]) > ROW_THRESHOLD:
            rows.append([w])
        else:
            rows[-1].append(w)
    for row in rows:
        row.sort(key=lambda w: w["left"])
    for row in rows:
        for start in range(len(row)):
            combined = ""
            for end in range(start, min(start + 12, len(row))):
                combined += row[end]["text"]
                if _fuzzy_match_chinese(target_text, combined):
                    # 找到目标文字在拼接串中的实际起止字符位置
                    sub_start = combined.find(target_text)
                    if sub_start < 0:
                        # 模糊匹配：找目标第一个字在拼接串中的位置
                        for ci, ch in enumerate(combined):
                            if ch in set(target_text):
                                sub_start = ci
                                break
                        else:
                            sub_start = 0
                    sub_end = combined.find(target_text)
                    sub_end = sub_start + len(target_text) if sub_end >= 0 else len(combined)
                    # 把字符位置映射回 word 索引
                    w_start, w_end = start, end
                    char_pos = 0
                    for k in range(start, end + 1):
                        w_len = len(row[k]["text"])
                        if w_start == start and char_pos + w_len > sub_start:
                            w_start = k
                        if char_pos + w_len >= sub_end:
                            w_end = k
                            break
                        char_pos += w_len
                    words_range = row[w_start:w_end + 1]
                    x = words_range[0]["left"] // scale
                    y = min(w["top"] for w in words_range) // scale
                    x2 = max(w["left"] + w["width"] for w in words_range) // scale
                    y2 = max(w["top"] + w["height"] for w in words_range) // scale
                    log(f"模糊拼接匹配 '{combined}' → 词[{w_start}:{w_end}] 位置: ({x},{y},{x2 - x},{y2 - y})")
                    return (x, y, x2 - x, y2 - y)

    # ---- 回退：裁剪目的地列表区域 + 4x 放大 + psm 6 ----
    # 诊断证明樱花岛需要4x才能读到，3x的psm6/psm11都不行，所以跳过3x回退直接走4x
    h_orig, w_orig = img.shape[:2]
    # 目的地名字列在屏幕 x=22%-35%, y=25%-78% 范围内（根据截图坐标校准）
    crop_y1, crop_y2 = int(h_orig * 0.25), int(h_orig * 0.78)
    crop_x1, crop_x2 = int(w_orig * 0.22), int(w_orig * 0.35)
    cropped = img[crop_y1:crop_y2, crop_x1:crop_x2]
    gray4 = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    gray4 = cv2.resize(gray4, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    inv4 = cv2.bitwise_not(gray4)
    data4 = pytesseract.image_to_data(inv4, lang=OCR_LANG,
                                       output_type=pytesseract.Output.DICT, config="--psm 6")
    words4 = []
    for i in range(len(data4["text"])):
        t = data4["text"][i].strip()
        c = int(data4["conf"][i])
        if c >= 5 and t:
            words4.append({"text": t, "left": data4["left"][i], "top": data4["top"][i],
                           "width": data4["width"][i], "height": data4["height"][i]})
    if words4:
        words4.sort(key=lambda w: (w["top"], w["left"]))
        rows4 = []
        for w in words4:
            if not rows4 or abs(w["top"] - rows4[-1][0]["top"]) > 80:
                rows4.append([w])
            else:
                rows4[-1].append(w)
        for row in rows4:
            row.sort(key=lambda w: w["left"])
            for start in range(len(row)):
                combined = ""
                for end in range(start, min(start + 12, len(row))):
                    combined += row[end]["text"]
                    if _fuzzy_match_chinese(target_text, combined):
                        sub_start = combined.find(target_text)
                        if sub_start < 0:
                            for ci, ch in enumerate(combined):
                                if ch in set(target_text):
                                    sub_start = ci
                                    break
                            else:
                                sub_start = 0
                        sub_end = combined.find(target_text)
                        sub_end = sub_start + len(target_text) if sub_end >= 0 else len(combined)
                        w_start, w_end = start, end
                        char_pos = 0
                        for k in range(start, end + 1):
                            w_len = len(row[k]["text"])
                            if w_start == start and char_pos + w_len > sub_start:
                                w_start = k
                            if char_pos + w_len >= sub_end:
                                w_end = k
                                break
                            char_pos += w_len
                        words_range = row[w_start:w_end + 1]
                        x = words_range[0]["left"] // 4 + crop_x1
                        y = min(w["top"] for w in words_range) // 4 + crop_y1
                        x2 = max(w["left"] + w["width"] for w in words_range) // 4 + crop_x1
                        y2 = max(w["top"] + w["height"] for w in words_range) // 4 + crop_y1
                        log(f"回退(psm6/4x/crop) 匹配 '{combined}' 位置: ({x},{y},{x2 - x},{y2 - y})")
                        return (x, y, x2 - x, y2 - y)

    return None


def find_text_center(img: np.ndarray, target_text: str):
    """查找文字中心点的屏幕坐标，返回 (cx, cy) 或 None"""
    result = find_text_position(img, target_text)
    if result:
        x, y, w, h = result
        cx = x + w // 2
        cy = y + h // 2
        return (cx, cy)
    return None


def find_text_fuzzy_center(img: np.ndarray, target_text: str):
    """模糊查找文字中心点，返回 (cx, cy) 或 None"""
    result = find_text_fuzzy_position(img, target_text)
    if result:
        x, y, w, h = result
        return (x + w // 2, y + h // 2)
    return None


def find_text_fuzzy_in_screenshot(target_text: str, save_name: str = "debug"):
    """截图并模糊查找文字，返回中心坐标或 None"""
    img = take_screenshot()
    save_debug_screenshot(img, save_name)
    return find_text_fuzzy_center(img, target_text)


def contains_text(img: np.ndarray, target_text: str) -> bool:
    """检测图像中是否包含指定文字"""
    processed = _preprocess_for_ocr(img)
    text = pytesseract.image_to_string(processed, lang=OCR_LANG, config="--psm 11")
    found = target_text in text
    log(f"OCR 匹配{'✓' if found else '✗'}: '{target_text}'")
    return found


def contains_any_text(img: np.ndarray, keywords: list) -> bool:
    """检测图像中是否包含任意一个关键词"""
    processed = _preprocess_for_ocr(img)
    text = pytesseract.image_to_string(processed, lang=OCR_LANG, config="--psm 11")
    for kw in keywords:
        if kw in text:
            log(f"OCR 匹配✓: '{kw}' (从候选: {keywords})")
            return True
    log(f"OCR 全部未匹配: {keywords}")
    return False


def find_any_text_position(img: np.ndarray, keywords: list):
    """查找任意一个关键词的位置，返回 (x, y, w, h) 或 None"""
    for kw in keywords:
        pos = find_text_position(img, kw)
        if pos:
            return pos
    return None


def contains_any_text_in_screenshot(keywords: list, save_name: str = "debug") -> bool:
    """截图并检测是否包含任意一个关键词"""
    img = take_screenshot()
    save_debug_screenshot(img, save_name)
    return contains_any_text(img, keywords)


def find_any_text_in_screenshot(keywords: list, save_name: str = "debug"):
    """截图并查找任意一个关键词，返回中心坐标或 None"""
    img = take_screenshot()
    save_debug_screenshot(img, save_name)
    return find_any_text_position(img, keywords)


def find_blue_button_text(img: np.ndarray, target_keywords: list):
    """通过蓝色区域检测 + 局部 OCR 查找按钮文字。
    适用于 Tesseract 全图 OCR 无法识别的蓝色按钮上的文字。
    返回中心坐标 (x, y) 或 None。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 蓝色按钮 HSV 范围（放宽阈值以覆盖更多蓝色阴影）
    lower_blue = np.array([80, 30, 80])
    upper_blue = np.array([140, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_img, w_img = img.shape[:2]

    # 按面积降序排列，优先检测大的按钮
    candidates = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        # 放宽条件：面积>200, 宽>30, 高>10
        if area > 200 and bw > 30 and bh > 10 and bw < 600 and bh < 200:
            candidates.append((x, y, bw, bh, area))
    candidates.sort(key=lambda t: t[4], reverse=True)

    # 两遍匹配：第一遍找精确匹配（文字长度接近关键词），第二宽松匹配
    fallback = None
    for x, y, bw, bh, area in candidates:
        roi = img[y:y + bh, x:x + bw]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_big = cv2.resize(roi_gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        roi_inv = cv2.bitwise_not(roi_big)
        for proc, label in [(roi_inv, "反转"), (roi_big, "正常")]:
            for psm in ["--psm 7", "--psm 6"]:
                text = pytesseract.image_to_string(proc, lang=OCR_LANG, config=psm).strip()
                for kw in target_keywords:
                    if kw in text:
                        cx, cy = x + bw // 2, y + bh // 2
                        # 精确匹配：OCR文字长度 <= 关键词长度 + 2
                        if len(text) <= len(kw) + 2:
                            log(f"蓝色按钮OCR({label},{psm}) 精确✓: '{kw}' in '{text}' at ({cx},{cy})")
                            return (cx, cy)
                        if fallback is None:
                            fallback = (cx, cy, kw, text)
    if fallback:
        cx, cy, kw, text = fallback
        log(f"蓝色按钮OCR 宽松✓: '{kw}' in '{text}' at ({cx},{cy})")
        return (cx, cy)
    log(f"蓝色区域检测: {len(candidates)} 个候选，均未匹配 {target_keywords}")
    return None


def find_blue_button_in_screenshot(keywords: list, save_name: str = "debug"):
    """截图并用蓝色区域检测查找按钮文字，返回中心坐标或 None"""
    img = take_screenshot()
    save_debug_screenshot(img, save_name)
    return find_blue_button_text(img, keywords)


# ============================================================
# 鼠标操作
# ============================================================

def click_position(x: int, y: int, duration: float = 0.2):
    """移动鼠标到指定位置并点击"""
    log(f"移动鼠标到 ({x}, {y}) 并点击")
    pyautogui.moveTo(x, y, duration=duration)
    time.sleep(0.05)
    pyautogui.click(x, y)


# ============================================================
# Windows 底层输入 (兼容 DirectInput 游戏)
# ============================================================

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120  # 每个滚轮刻度 = 120


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("input", _INPUT_UNION),
    ]


def _send_mouse_wheel(scroll_amount: int):
    """通过 SendInput 发送鼠标滚轮事件（兼容 DirectInput 游戏）
    scroll_amount: 正数=向上滚动, 负数=向下滚动
    """
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.input.mi.dx = 0
    inp.input.mi.dy = 0
    inp.input.mi.mouseData = scroll_amount & 0xFFFFFFFF  # DWORD 无符号
    inp.input.mi.dwFlags = MOUSEEVENTF_WHEEL
    inp.input.mi.time = 0
    inp.input.mi.dwExtraInfo = ctypes.pointer(extra)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def scroll_down(pages: int = 1):
    """控制滚轮向下翻页（使用 SendInput 底层 API，兼容游戏）"""
    # 每页滚动 5 个刻度 = 5 * 120 = 600, 负数=向下
    scroll_val = -WHEEL_DELTA * 5 * pages
    log(f"滚轮向下翻 {pages} 页 (scroll={scroll_val})")
    _send_mouse_wheel(scroll_val)


def scroll_up(pages: int = 1):
    """控制滚轮向上翻页"""
    scroll_val = WHEEL_DELTA * 5 * pages
    log(f"滚轮向上翻 {pages} 页 (scroll={scroll_val})")
    _send_mouse_wheel(scroll_val)


# 按键映射: name -> (virtual_key, scan_code)
KEY_MAP = {
    "f":       (0x46, 0x21),
    "e":       (0x45, 0x12),
    "x":       (0x58, 0x2D),
    "enter":   (0x0D, 0x1C),
    "esc":     (0x1B, 0x01),
    "escape":  (0x1B, 0x01),
    "space":   (0x20, 0x39),
    "tab":     (0x09, 0x0F),
    "up":      (0x26, 0x48),
    "down":    (0x28, 0x50),
    "left":    (0x25, 0x4B),
    "right":   (0x27, 0x4D),
}


def _find_game_window():
    """查找 Palworld 游戏窗口句柄"""
    hwnd = ctypes.windll.user32.FindWindowW(None, "Pal")
    if hwnd:
        return hwnd
    # 备用查找
    hwnd = ctypes.windll.user32.FindWindowW(None, "Palworld")
    return hwnd


def _send_input_key(vk, scan):
    """通过 SendInput 发送按键（需要管理员权限）"""
    def _send(flags):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.input.ki.wVk = vk
        inp.input.ki.wScan = scan
        inp.input.ki.dwFlags = flags
        return ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    r1 = _send(0)
    time.sleep(0.08)
    r2 = _send(KEYEVENTF_KEYUP)
    return r1 == 1


def _send_postmessage_key(hwnd, vk, scan):
    """通过 PostMessage 发送按键到指定窗口（无需焦点）"""
    lparam_down = (scan << 16) | 1
    lparam_up = (scan << 16) | 1 | (1 << 30) | (1 << 31)
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam_down)
    time.sleep(0.08)
    ctypes.windll.user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam_up)


def press_key(key: str):
    """发送按键：先激活窗口用 SendInput，失败则用 PostMessage"""
    log(f"按下按键: {key}")

    entry = KEY_MAP.get(key.lower())
    if entry is None:
        log(f"未知按键: {key}，回退使用 pyautogui")
        pyautogui.press(key)
        return

    vk, scan = entry

    # 方法 1: 先激活游戏窗口，再 SendInput
    hwnd = _find_game_window()
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)

    if _send_input_key(vk, scan):
        log(f"  -> SendInput 成功")
        return

    # 方法 2: SendInput 失败，用 PostMessage
    if hwnd:
        log(f"  -> SendInput 失败，改用 PostMessage")
        _send_postmessage_key(hwnd, vk, scan)
    else:
        log(f"  -> 未找到游戏窗口，尝试 pyautogui")
        pyautogui.press(key)


# ============================================================
# 目的地配置
# ============================================================

# 不需要翻页的目的地 (第一页)
DESTINATIONS_PAGE1 = [
    "草原的洞穴",
    "森林的秘境",
    "火山的灼热洞穴",
    "沙漠的隐秘遗迹",
    "雪山的冻结洞穴",
    "樱花岛的灵花洞穴",
]

# 需要翻页的目的地 (第二页)
DESTINATIONS_PAGE2 = [
    "天坠魔窟",
    "天阳乡浮岛",
    "世界树地下都市遗址",
]


# ============================================================
# 核心自动化逻辑
# ============================================================

class AutoExpedition:
    def __init__(self):
        self.running = False
        self._lock = threading.Lock()
        self.destination = "草原的洞穴"  # 默认目的地
        self.original_time = None

    def set_destination(self, dest: str):
        self.destination = dest

    def start(self):
        """启动自动化流程"""
        if not self._lock.acquire(blocking=False):
            log("已在运行中，忽略重复触发")
            return
        self.running = True
        log("=" * 50)
        log(f"启动自动化流程，目的地: {self.destination}")
        log("=" * 50)
        threading.Thread(target=self._run_loop, daemon=True).start()

    def stop(self):
        """停止自动化流程"""
        self.running = False
        log("已请求停止，等待当前循环结束...")

    def _run_loop(self):
        """主循环：重复执行远征流程"""
        try:
            while self.running:
                success = self._run_once()
                if not self.running:
                    break
                if not success:
                    log("本次流程失败，停止运行")
                    break
                log("本次流程完成，准备下一轮...")
                time.sleep(0.5)
        finally:
            self.running = False
            self._lock.release()
            log("自动化流程已结束")

    def _run_once(self) -> bool:
        """执行一次完整的远征流程，返回是否成功"""
        self.original_time = None
        self._rollback_mono = 0
        try:
            return self._run_once_inner()
        finally:
            # 无论成功还是失败，都确保恢复系统时间（补偿经过的时间）
            if self.original_time:
                elapsed = time.monotonic() - self._rollback_mono
                restored = adjust_time(self.original_time, elapsed)
                if set_system_time(restored):
                    log(f"[安全恢复] 已恢复至: {format_time(restored)} (补偿 {elapsed:.3f}s)")
                else:
                    log("[安全恢复] 恢复时间失败！请手动调整")
                self.original_time = None

    def _run_once_inner(self) -> bool:
        """执行一次完整的远征流程（内部实现），返回是否成功"""

        # ---- 步骤 2：等待后按下 F 键 ----
        log(f"[步骤2] 等待 {DELAYS['pre_action']}s 后按下 F 键")
        time.sleep(DELAYS["pre_action"])
        press_key("f")
        time.sleep(0.1)
        press_key("f")  # 再按一次确保游戏接收到

        # ---- 步骤 3：等待后截图 ----
        log(f"[步骤3] 等待 {DELAYS['post_screenshot']}s 后截图")
        time.sleep(DELAYS["post_screenshot"])

        # ---- 步骤 4：检测远征目的地界面 ----
        # OCR 对"远征目的地"识别不佳，改用多个可识别的关键词
        EXPEDITION_KEYWORDS = ["远征目的地", "需要时间", "指派", "派遣帕鲁", "目的地"]
        log("[步骤4] 检测远征目的地界面")
        img = take_screenshot()
        save_debug_screenshot(img, "step4")

        if not contains_any_text(img, EXPEDITION_KEYWORDS):
            log(f"第一次未检测到远征界面，等待 {DELAYS['detection_retry']*2}s 后重试...")
            time.sleep(DELAYS["detection_retry"] * 2)
            img2 = take_screenshot()
            save_debug_screenshot(img2, "step4_retry")
            if not contains_any_text(img2, EXPEDITION_KEYWORDS):
                log("第二次仍未检测到远征界面，停止运行")
                return False

        # ---- 步骤 5：检测派遣界面 ----
        DISPATCH_KEYWORDS = ["请选择派遣帕鲁远征的目的地", "派遣帕鲁远征", "选择目的", "目的地"]
        log("[步骤5] 检测派遣界面")
        img = take_screenshot()
        save_debug_screenshot(img, "step5")

        if contains_any_text(img, DISPATCH_KEYWORDS):
            # ---- 步骤 6：根据目的地选择 ----
            log("[步骤6] 检测到派遣界面，准备选择目的地")
            if not self._step6_select_destination():
                return False
        else:
            log("未检测到派遣界面，跳转到步骤7")

        # ---- 步骤 7：检测并点击 "自动指派" ----
        log(f"[步骤7] 等待 {DELAYS['pre_action']}s 后检测 '自动指派'")
        time.sleep(DELAYS["pre_action"])

        # 优先用蓝色区域检测（只用'自动指派'精确匹配，避免匹配到'指派时的例外设置'）
        AUTO_KEYWORDS = ["自动指派"]
        pos = find_blue_button_in_screenshot(AUTO_KEYWORDS, "step7")
        if pos:
            click_position(pos[0], pos[1])
        else:
            log("蓝色按钮检测未找到，用全图OCR+行拼接匹配...")
            time.sleep(DELAYS["detection_retry"])
            img = take_screenshot()
            save_debug_screenshot(img, "step7_retry")
            pos = find_text_position(img, "自动指派")
            if not pos:
                pos = find_text_fuzzy_position(img, "自动指派")
            if not pos:
                log("仍未找到 '自动指派'，停止运行")
                return False
            cx, cy = pos[0] + pos[2] // 2, pos[1] + pos[3] // 2
            click_position(cx, cy)

        # ---- 步骤 7.5：等待派遣帕鲁界面加载 ----
        log(f"[步骤7.5] 等待 {DELAYS['step7_dispatch_wait']}s，检测派遣帕鲁界面")
        time.sleep(DELAYS["step7_dispatch_wait"])
        img = take_screenshot()
        save_debug_screenshot(img, "step7_5")
        if contains_any_text(img, ["派遣帕鲁", "选择帕鲁", "帕鲁"]):
            log("检测到派遣帕鲁界面，等待自动指派完成...")
            # 自动指派已点过，等几秒让它自动选完帕鲁
            time.sleep(2.0)

        # ---- 步骤 8：回拨系统时间 1 小时 ----
        log(f"[步骤8] 等待 {DELAYS['pre_action']}s 后回拨系统时间 1 小时")
        time.sleep(DELAYS["pre_action"])
        self.original_time = rollback_time_one_hour()
        if self.original_time is None:
            log("时间回拨失败，停止运行")
            return False
        self._rollback_mono = time.monotonic()  # 记录回拨时刻

        # ---- 步骤 9：检测并点击 "开始" ----
        log(f"[步骤9] 等待 {DELAYS['pre_action']}s 后检测 '开始'")
        time.sleep(DELAYS["pre_action"])

        # "开始" 按钮是蓝色的，全图 OCR 可能识别不出，优先用蓝色区域检测
        START_KEYWORDS = ["开始", "开启", "启程"]
        pos = None

        # 方法1: 蓝色区域检测 + 局部 OCR（最可靠）
        pos = find_blue_button_in_screenshot(START_KEYWORDS, "step9")

        # 方法2: 全图 OCR 回退
        if not pos:
            log("蓝色区域未找到 '开始'，尝试全图 OCR...")
            img = take_screenshot()
            save_debug_screenshot(img, "step9_ocr")
            pos = find_any_text_position(img, START_KEYWORDS)

        if not pos:
            log("第一次未找到 '开始'，重试...")
            time.sleep(DELAYS["detection_retry"])
            pos = find_blue_button_in_screenshot(START_KEYWORDS, "step9_retry")
            if not pos:
                img = take_screenshot()
                save_debug_screenshot(img, "step9_retry_ocr")
                pos = find_any_text_position(img, START_KEYWORDS)
            if not pos:
                log("第二次仍未找到 '开始'，停止运行")
                return False
        click_position(pos[0], pos[1])

        # ---- 步骤 9.5：恢复系统时间（补偿经过的时间，精确到毫秒） ----
        log(f"[步骤9.5] 等待 {DELAYS['time_restore_wait']}s 后恢复系统时间")
        time.sleep(DELAYS["time_restore_wait"])
        if self.original_time:
            elapsed = time.monotonic() - self._rollback_mono
            restored = adjust_time(self.original_time, elapsed)
            if set_system_time(restored):
                log(f"已恢复至: {format_time(restored)} (补偿 {elapsed:.3f}s)")
            else:
                log("恢复时间失败！请手动调整")
            self.original_time = None

        # ---- 步骤 10-12：按F → 检测物品栏 → 没找到则重试按F ----
        menu_opened = False
        for f_attempt in range(3):
            wait_t = 0.5 if f_attempt == 0 else DELAYS["detection_retry"]
            log(f"[步骤10] 等待 {wait_t:.1f}s 后按下 F 键 (第{f_attempt + 1}次)")
            time.sleep(wait_t)
            press_key("f")
            time.sleep(DELAYS["step12_detect_wait"])
            img = take_screenshot()
            save_debug_screenshot(img, f"step12_f{f_attempt}")
            if contains_any_text(img, ["物品栏"]):
                log("检测到物品栏")
                menu_opened = True
                break
            log(f"第{f_attempt + 1}次F后未检测到 '物品栏'，重试...")

        if not menu_opened:
            log("3次按F后仍未检测到物品栏，跳过取奖励")

        # 按 X 取走全部奖励
        log("按下 X 取走全部奖励")
        press_key("x")
        time.sleep(DELAYS["step12_reward_wait"])

        # 按 ESC 关闭菜单
        log("按下 ESC 关闭菜单")
        press_key("escape")
        time.sleep(DELAYS["step12_close_wait"])

        log("本次远征流程完成 ✓")
        return True

    def _step6_select_destination(self) -> bool:
        """步骤6：选择目的地（使用模糊匹配容忍OCR错字）"""
        dest = self.destination
        needs_page2 = dest in DESTINATIONS_PAGE2

        screen_w, screen_h = pyautogui.size()
        list_x, list_y = screen_w // 2, screen_h // 2

        max_scrolls = 4  # 最多滚动次数

        # PAGE2 目的地先翻一整页
        if needs_page2:
            log(f"目的地 '{dest}' 在第二页，先向下翻页...")
            pyautogui.moveTo(list_x, list_y, duration=DELAYS["click_move"])
            time.sleep(0.1)
            scroll_down()
            time.sleep(DELAYS["scroll_wait"])

        # 第一次尝试（不滚动）
        pos = find_text_fuzzy_in_screenshot(dest, "step6")
        if pos:
            click_position(pos[0], pos[1])
            return True

        # 逐步向下滚动搜索
        for i in range(max_scrolls):
            log(f"未找到，向下滚动... (第{i + 1}次)")
            pyautogui.moveTo(list_x, list_y, duration=DELAYS["click_move"])
            time.sleep(0.1)
            scroll_down()
            time.sleep(DELAYS["scroll_wait"])
            pos = find_text_fuzzy_in_screenshot(dest, f"step6_scroll{i + 1}")
            if pos:
                click_position(pos[0], pos[1])
                return True

        log(f"未找到目的地 '{dest}'（滚动{max_scrolls}次后仍失败），停止运行")
        return False


# ============================================================
# 热键监听
# ============================================================

_expedition = AutoExpedition()
_listener = None
_app_ref = None  # App 实例引用（用于从监听线程更新 UI）


def on_press(key):
    global _expedition, _hotkey_binding
    try:
        if _hotkey_binding:
            if key == keyboard.Key.esc:
                _apply_hotkey(None)
            else:
                _apply_hotkey(key)
            _hotkey_binding = False
            return
        if HOTKEY is not None and key == HOTKEY:
            if _expedition.running:
                if _app_ref:
                    _app_ref.root.after(0, _app_ref._stop)
            else:
                if _app_ref:
                    _app_ref.root.after(0, _app_ref._start)
    except Exception as e:
        log(f"热键处理错误: {e}")


def _apply_hotkey(key):
    """应用新热键（从 on_press 调用）"""
    global HOTKEY
    HOTKEY = key
    display = _key_to_display(key)
    save_delays_config()
    log(f"热键已设置为: {display}")
    # 通过 after 在主线程更新 UI
    if _app_ref:
        _app_ref.root.after(0, _app_ref._apply_hotkey_ui, key)


def start_hotkey_listener():
    """启动热键监听器"""
    global _listener
    _listener = keyboard.Listener(on_press=on_press)
    _listener.daemon = True
    _listener.start()
    log(f"热键监听已启动 (按 {_key_to_display(HOTKEY)} 开始/停止)")


# ============================================================
# GUI 界面
# ============================================================

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"PalFastExpeditions {VERSION}")
        self.root.geometry("700x750")
        self.root.resizable(True, True)

        # 设置图标和样式
        style = ttk.Style()
        style.theme_use("clam")

        self._build_ui()
        self._setup_logging()

        # 保存 App 引用（供热键回调更新 UI）
        global _app_ref
        _app_ref = self

        # 启动热键监听
        start_hotkey_listener()

    def _build_ui(self):
        """构建 UI"""
        # ---- 顶部：目的地选择 ----
        frame_top = ttk.LabelFrame(self.root, text="目的地设置", padding=10)
        frame_top.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_top, text="选择远征目的地:").pack(side="left")

        all_destinations = DESTINATIONS_PAGE1 + DESTINATIONS_PAGE2
        self.dest_var = tk.StringVar(value=all_destinations[0])
        dest_combo = ttk.Combobox(
            frame_top, textvariable=self.dest_var,
            values=all_destinations, state="readonly", width=25
        )
        dest_combo.pack(side="left", padx=10)
        dest_combo.bind("<<ComboboxSelected>>", self._on_dest_change)

        # ---- 中部：控制按钮 ----
        frame_mid = ttk.LabelFrame(self.root, text="控制", padding=10)
        frame_mid.pack(fill="x", padx=10, pady=5)

        self.btn_start = ttk.Button(frame_mid, text="开始", command=self._toggle)
        self.btn_start.pack(side="left", padx=5)

        ttk.Button(frame_mid, text="停止", command=self._stop).pack(side="left", padx=5)

        self.hotkey_btn = ttk.Button(
            frame_mid, text=f"热键: {_key_to_display(HOTKEY)}",
            command=self._start_bind_hotkey, width=16
        )
        self.hotkey_btn.pack(side="left", padx=15)

        self.status_label = ttk.Label(frame_mid, text="状态: 就绪", foreground="gray")
        self.status_label.pack(side="right", padx=10)

        # ---- Tesseract 路径设置 ----
        frame_tess = ttk.LabelFrame(self.root, text="Tesseract 设置", padding=10)
        frame_tess.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_tess, text="Tesseract 路径:").pack(side="left")
        self.tess_var = tk.StringVar(value=pytesseract.pytesseract.tesseract_cmd)
        tess_entry = ttk.Entry(frame_tess, textvariable=self.tess_var, width=50)
        tess_entry.pack(side="left", padx=5)
        ttk.Button(frame_tess, text="应用", command=self._apply_tess_path).pack(side="left")

        # ---- 缓存管理 ----
        frame_cache = ttk.LabelFrame(self.root, text="缓存管理", padding=10)
        frame_cache.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_cache, text=f"配置目录: {CONFIG_DIR}", foreground="gray").pack(anchor="w")
        self.cache_label = ttk.Label(frame_cache, text="截图缓存: 计算中...")
        self.cache_label.pack(side="left")

        ttk.Button(frame_cache, text="刷新", command=self._refresh_cache_size).pack(side="left", padx=10)
        ttk.Button(frame_cache, text="清除缓存", command=self._clear_cache).pack(side="left", padx=5)

        self._refresh_cache_size()

        # ---- 延迟设置 ----
        frame_delay = ttk.LabelFrame(self.root, text="延迟设置 (秒)", padding=10)
        frame_delay.pack(fill="x", padx=10, pady=5)

        self.delay_vars = {}
        delay_keys = list(DELAY_LABELS.keys())
        cols = 3
        for i, key in enumerate(delay_keys):
            row, col = divmod(i, cols)
            sub = ttk.Frame(frame_delay)
            sub.grid(row=row, column=col, padx=5, pady=2, sticky="w")
            ttk.Label(sub, text=f"{DELAY_LABELS[key]}:").pack(side="left")
            var = tk.StringVar(value=str(DELAYS[key]))
            entry = ttk.Entry(sub, textvariable=var, width=6)
            entry.pack(side="left", padx=3)
            self.delay_vars[key] = var

        btn_delay_frame = ttk.Frame(frame_delay)
        btn_delay_frame.grid(row=divmod(len(delay_keys), cols)[0] + 1, column=0, columnspan=cols, pady=5)
        ttk.Button(btn_delay_frame, text="保存延迟设置", command=self._save_delays).pack(side="left", padx=5)
        ttk.Button(btn_delay_frame, text="恢复默认", command=self._reset_delays).pack(side="left", padx=5)

        # ---- 底部：日志 ----
        frame_log = ttk.LabelFrame(self.root, text="运行日志", padding=5)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_text = tk.Text(frame_log, height=15, wrap="word", font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(frame_log, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ---- 底部提示 ----
        hk_name = _key_to_display(HOTKEY)
        self.tip_label = ttk.Label(
            self.root,
            text=f"按 {hk_name} 开始/停止",
            foreground="blue"
        )
        self.tip_label.pack(pady=3)

    def _setup_logging(self):
        """将日志输出到 UI"""
        global _log_callback
        _log_callback = self._append_log

    def _append_log(self, msg: str):
        """追加日志到文本框"""
        def _update():
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
        self.root.after(0, _update)

    def _on_dest_change(self, event=None):
        """目的地变更"""
        dest = self.dest_var.get()
        _expedition.set_destination(dest)
        log(f"目的地已切换为: {dest}")

    def _toggle(self):
        """切换开始/停止"""
        if _expedition.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        """开始"""
        _expedition.set_destination(self.dest_var.get())
        _expedition.start()
        self.status_label.config(text="状态: 运行中", foreground="green")
        self.root.iconify()  # 最小化窗口

    def _stop(self):
        """停止"""
        _expedition.stop()
        self.status_label.config(text="状态: 已停止", foreground="red")
        self.root.deiconify()  # 恢复窗口

    def _start_bind_hotkey(self):
        """开始绑定热键：下一个按键将设为热键"""
        global _hotkey_binding
        _hotkey_binding = True
        self.hotkey_btn.config(text="请按键...")
        log("等待设置热键... (按ESC取消热键)")

    def _apply_hotkey_ui(self, key):
        """热键绑定完成后更新 UI"""
        display = _key_to_display(key)
        self.hotkey_btn.config(text=f"热键: {display}")
        hk_name = _key_to_display(HOTKEY)
        self.tip_label.config(
            text=f"提示: 按 {hk_name} 开始/停止 | 确保以管理员权限运行 | 鼠标移到屏幕左上角可紧急停止"
        )

    def _apply_tess_path(self):
        """应用 Tesseract 路径"""
        path = self.tess_var.get().strip()
        if os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            log(f"Tesseract 路径已更新: {path}")
            messagebox.showinfo("成功", f"Tesseract 路径已更新:\n{path}")
        else:
            messagebox.showerror("错误", f"文件不存在:\n{path}")

    def _get_cache_size(self):
        """计算 screenshots 目录大小"""
        total = 0
        count = 0
        if os.path.isdir(SCREENSHOT_DIR):
            for f in os.listdir(SCREENSHOT_DIR):
                fp = os.path.join(SCREENSHOT_DIR, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
                    count += 1
        return total, count

    def _format_size(self, size_bytes):
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _refresh_cache_size(self):
        """刷新缓存大小显示"""
        total, count = self._get_cache_size()
        self.cache_label.config(text=f"截图缓存: {count} 个文件, {self._format_size(total)}")

    def _clear_cache(self):
        """清除截图缓存"""
        total, count = self._get_cache_size()
        if count == 0:
            messagebox.showinfo("提示", "缓存已经是空的")
            return
        if messagebox.askyesno("确认", f"确定删除 {count} 个截图文件 ({self._format_size(total)})？"):
            deleted = 0
            for f in os.listdir(SCREENSHOT_DIR):
                fp = os.path.join(SCREENSHOT_DIR, f)
                if os.path.isfile(fp):
                    try:
                        os.remove(fp)
                        deleted += 1
                    except Exception:
                        pass
            log(f"已清除 {deleted} 个截图缓存文件")
            self._refresh_cache_size()

    def _save_delays(self):
        """保存延迟设置"""
        global DELAYS
        try:
            for key, var in self.delay_vars.items():
                val = float(var.get())
                if val < 0:
                    raise ValueError(f"{DELAY_LABELS[key]} 不能为负数")
                DELAYS[key] = val
            save_delays_config()
            messagebox.showinfo("成功", "延迟设置已保存")
        except ValueError as e:
            messagebox.showerror("错误", f"输入无效: {e}")

    def _reset_delays(self):
        """恢复默认延迟"""
        global DELAYS
        DELAYS = dict(DEFAULT_DELAYS)
        for key, var in self.delay_vars.items():
            var.set(str(DELAYS[key]))
        save_delays_config()
        log("延迟设置已恢复默认")

    def run(self):
        """运行 GUI"""
        self.root.mainloop()


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print(f"  PalFastExpeditions {VERSION}")
    print("=" * 50)
    print()
    print("  热键: PageDown  →  开始/停止")
    print("  紧急停止: 鼠标移到屏幕左上角")
    print()
    print(f"  配置目录: {CONFIG_DIR}")
    print()
    print("  ⚠ 请确保以管理员权限运行！")
    print("  ⚠ 请确保 Tesseract OCR 已安装！")
    print("=" * 50)
    print()

    app = App()
    app.run()
