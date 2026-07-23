"""
PalFastExpeditions - 帕鲁远征自动化工具
使用 OpenCV + RapidOCR + PyAutoGUI 实现屏幕文字识别与自动点击
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
from rapidocr_onnxruntime import RapidOCR
from pynput import keyboard
from PIL import ImageGrab

# ============================================================
# 全局配置
# ============================================================

VERSION = "v0.3-beta"

# RapidOCR 引擎 (ONNX Runtime, CPU/DirectML 加速)
import onnxruntime as ort
_DML_AVAILABLE = "DmlExecutionProvider" in ort.get_available_providers()
_ocr_use_gpu = _DML_AVAILABLE  # 默认：有DirectML就用GPU，否则CPU
_ocr_engine = None
_ocr_backend = "CPU"


LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
# 日志文件精确到时分秒: logs/2026-07-23_183045.log
_log_file_path = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log")
_log_file = None


def _get_log_file():
    """懒加载日志文件句柄"""
    global _log_file
    if _log_file is None:
        try:
            _log_file = open(_log_file_path, "a", encoding="utf-8")
        except Exception:
            pass
    return _log_file


def _log_early(msg: str):
    """模块加载时的日志（log() 尚未定义时的 fallback）"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    print(line)
    f = _get_log_file()
    if f:
        try:
            f.write(line + "\n")
            f.flush()
        except Exception:
            pass


def _init_ocr_engine(use_gpu: bool = None):
    """初始化或切换 OCR 引擎
    use_gpu: True=GPU(DirectML), False=CPU, None=自动检测
    返回 (engine, backend_name)
    """
    global _ocr_engine, _ocr_backend, _ocr_use_gpu
    if use_gpu is None:
        use_gpu = _DML_AVAILABLE
    if use_gpu and not _DML_AVAILABLE:
        _log_early("[OCR] DirectML 不可用，回退到 CPU 模式")
        use_gpu = False
    _ocr_use_gpu = use_gpu
    _ocr_engine = RapidOCR(det_use_dml=use_gpu, rec_use_dml=use_gpu, cls_use_dml=use_gpu)
    _ocr_backend = "DirectML (GPU)" if use_gpu else "CPU"
    _log_early(f"[OCR] 引擎已初始化: {_ocr_backend}")
    return _ocr_engine, _ocr_backend


def _ocr_self_check():
    """RapidOCR 自检：生成一张测试图片，验证引擎可用"""
    try:
        import numpy as _np
        test_img = _np.ones((100, 300, 3), dtype=_np.uint8) * 255
        import cv2 as _cv2
        _cv2.putText(test_img, "TEST", (30, 70), _cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 3)
        t0 = time.time()
        result, _ = _ocr_engine(test_img)
        elapsed = time.time() - t0
        if result:
            texts = [item[1] for item in result]
            _log_early(f"[OCR] 自检通过 ({elapsed:.2f}s): 识别到 {texts}")
            return True
        else:
            _log_early(f"[OCR] 自检警告 ({elapsed:.2f}s): 未识别到文字（引擎可能正常，测试图太简单）")
            return True  # 引擎能运行就算通过
    except Exception as e:
        _log_early(f"[OCR] 自检失败: {e}")
        return False


# 启动时自动初始化
_init_ocr_engine()
_ocr_self_check()

# OCR 图像缩放：2560x1440 全图太慢，缩到最大1920宽再识别
_OCR_MAX_WIDTH = 1920

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

# 多选目的地配置（6个槽位，None 表示"无"）
MULTI_DESTINATIONS = [None] * 6

# 当前延迟值（运行时使用）
DELAYS = dict(DEFAULT_DELAYS)


def load_delays_config():
    """从 config/delays.json 加载延迟配置、热键和OCR设置"""
    global DELAYS, HOTKEY, MULTI_DESTINATIONS, _ocr_use_gpu
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
            if "multi_destinations" in data:
                saved = data["multi_destinations"]
                for i in range(min(len(saved), 6)):
                    MULTI_DESTINATIONS[i] = saved[i]  # None 或字符串
                print(f"[配置] 已加载多选目的地: {[d or '（无）' for d in MULTI_DESTINATIONS]}")
            if "ocr_use_gpu" in data:
                _ocr_use_gpu = bool(data["ocr_use_gpu"])
                print(f"[配置] 已加载OCR模式: {'GPU' if _ocr_use_gpu else 'CPU'}")
        except Exception as e:
            print(f"[配置] 加载配置失败: {e}，使用默认值")


def save_delays_config():
    """保存延迟配置、热键和OCR设置到 config/delays.json"""
    try:
        with open(DELAYS_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "delays": DELAYS,
                "hotkey": _hotkey_to_config(HOTKEY),
                "multi_destinations": MULTI_DESTINATIONS,
                "ocr_use_gpu": _ocr_use_gpu,
            }, f, ensure_ascii=False, indent=4)
        log(f"配置已保存: {DELAYS_PATH}")
    except Exception as e:
        log(f"保存配置失败: {e}")


# 启动时加载配置
load_delays_config()
# 加载配置后，如果有保存的 OCR 模式设置，重新初始化引擎
_init_ocr_engine(use_gpu=_ocr_use_gpu)

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


def log(msg: str, verbose: bool = False):
    """打印日志并推送到 UI 和日志文件
    verbose=True: 只写文件和控制台，不显示在 UI（调试信息）
    """
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] {msg}"
    print(line)
    if not verbose and _log_callback:
        _log_callback(line)
    f = _get_log_file()
    if f:
        try:
            f.write(line + "\n")
            f.flush()
        except Exception:
            pass


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


def _rapid_ocr(img: np.ndarray) -> list:
    """运行 RapidOCR，返回格式化结果列表 [{text, left, top, width, height, conf}]
    自动缩放大图以提升识别速度，坐标已映射回原图尺寸。"""
    h_img, w_img = img.shape[:2]
    scale = 1.0
    ocr_img = img
    if w_img > _OCR_MAX_WIDTH:
        scale = _OCR_MAX_WIDTH / w_img
        ocr_img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    result, _ = _ocr_engine(ocr_img)
    items = []
    if result:
        for box, text, conf in result:
            text = text.strip()
            if not text:
                continue
            # box 是4个角点 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            left = int(min(xs) / scale)
            top = int(min(ys) / scale)
            right = int(max(xs) / scale)
            bottom = int(max(ys) / scale)
            items.append({
                "text": text,
                "left": left,
                "top": top,
                "width": right - left,
                "height": bottom - top,
                "conf": float(conf),
            })
    return items


def _rapid_ocr_text(img: np.ndarray) -> str:
    """运行 RapidOCR，返回拼接的文字"""
    items = _rapid_ocr(img)
    return " ".join(item["text"] for item in items)


def _group_items_by_row(items: list, threshold: int = 30) -> list:
    """将 OCR 结果按垂直位置分组为行"""
    if not items:
        return []
    sorted_items = sorted(items, key=lambda x: x["top"])
    rows = [[sorted_items[0]]]
    for item in sorted_items[1:]:
        if abs(item["top"] - rows[-1][-1]["top"]) < threshold:
            rows[-1].append(item)
        else:
            rows.append([item])
    return rows


def find_text_position(img: np.ndarray, target_text: str):
    """在图像中查找目标文字位置，返回 (x, y, w, h) 或 None。
    使用 RapidOCR 直接识别原图，无需预处理。"""
    items = _rapid_ocr(img)
    log(f"RapidOCR 共识别 {len(items)} 条文字", verbose=True)

    # --- Pass 1: 精确子串匹配 ---
    for item in items:
        if target_text in item["text"]:
            log(f"精确匹配 '{target_text}' in '{item["text"]}' → ({item['left']},{item['top']},{item['width']},{item['height']})", verbose=True)
            return (item["left"], item["top"], item["width"], item["height"])

    # --- Pass 2: 行拼接匹配 ---
    rows = _group_items_by_row(items)
    for row_items in rows:
        row_items.sort(key=lambda x: x["left"])
        combined = "".join(i["text"] for i in row_items)
        if target_text in combined:
            x = row_items[0]["left"]
            y = min(i["top"] for i in row_items)
            w = max(i["left"] + i["width"] for i in row_items) - x
            h = max(i["top"] + i["height"] for i in row_items) - y
            log(f"行拼接匹配 '{target_text}' in '{combined}' → ({x},{y},{w},{h})", verbose=True)
            return (x, y, w, h)

    log(f"未找到文字: '{target_text}'", verbose=True)
    return None


def _fuzzy_match_chinese(target: str, text: str, min_ratio: float = 0.75) -> bool:
    """模糊匹配中文：
    1. 精确子串匹配
    2. 目标前缀匹配（取目标前3个字看是否出现在文本中）
    3. 字符重叠率匹配（共同字符数/目标字符数 >= min_ratio，默认0.75）
    """
    # 精确子串
    if target in text:
        return True
    # 前缀匹配：取前 max(3, 60%) 个字，要求出现在文本开头
    prefix_len = max(3, int(len(target) * 0.6))
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
    items = _rapid_ocr(img)
    if not items:
        log("RapidOCR 未识别到任何文字", verbose=True)
        return None

    # --- 精确子串匹配 ---
    for item in items:
        if target_text in item["text"]:
            log(f"模糊-精确匹配 '{target_text}' in '{item['text']}' conf={item['conf']:.2f}", verbose=True)
            return (item["left"], item["top"], item["width"], item["height"])

    # --- 单条模糊匹配 ---
    for item in items:
        if _fuzzy_match_chinese(target_text, item["text"]):
            log(f"模糊匹配找到 '{item['text']}' conf={item['conf']:.2f}", verbose=True)
            return (item["left"], item["top"], item["width"], item["height"])

    # --- 行拼接后模糊匹配 ---
    rows = _group_items_by_row(items)
    for row_items in rows:
        row_items.sort(key=lambda x: x["left"])
        combined = "".join(i["text"] for i in row_items)
        if _fuzzy_match_chinese(target_text, combined):
            x = row_items[0]["left"]
            y = min(i["top"] for i in row_items)
            w = max(i["left"] + i["width"] for i in row_items) - x
            h = max(i["top"] + i["height"] for i in row_items) - y
            log(f"模糊行拼接匹配 '{combined}' → ({x},{y},{w},{h})", verbose=True)
            return (x, y, w, h)

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


def _find_by_landmark(img: np.ndarray, target_text: str):
    """地标定位法：当 OCR 无法识别目标文字时，
    通过检测相邻的可识别目的地来推算目标的点击位置。
    支持多层地标回退。返回 (cx, cy) 或 None。
    """
    if target_text not in DESTINATION_LANDMARKS:
        return None
    h_img, w_img = img.shape[:2]
    landmarks = DESTINATION_LANDMARKS[target_text]
    for landmark_name, offset in landmarks:
        pos = find_text_fuzzy_position(img, landmark_name)
        if not pos:
            continue
        x, y, w, h = pos
        # 过滤掉工具窗口中的误检：游戏列表区域的文字高度至少 20px
        # 且位置应在游戏画面中心偏左区域（x < 屏幕50%）
        if h < 20 or x > w_img * 0.5:
            log(f"地标法: '{landmark_name}' 位置({x},{y},{w},{h}) 不在游戏列表区域，跳过", verbose=True)
            continue
        # 列表项高度估算：地标文字高度 * 3.5（经验值），最少 100px
        item_height = max(int(h * 3.5), 100)
        target_cx = x + w // 2
        target_cy = y + h // 2 + offset * item_height
        # 确保不超出屏幕
        target_cy = max(50, min(target_cy, h_img - 50))
        log(f"地标法: '{landmark_name}' 在({x},{y},{w},{h}), "
            f"推算 '{target_text}' 在({target_cx},{target_cy}), 偏移{offset}项", verbose=True)
        return (target_cx, target_cy)
    return None


def contains_text(img: np.ndarray, target_text: str) -> bool:
    """检测图像中是否包含指定文字"""
    text = _rapid_ocr_text(img)
    found = target_text in text
    log(f"RapidOCR 匹配{'OK' if found else 'FAIL'}: '{target_text}'", verbose=True)
    return found


def contains_any_text(img: np.ndarray, keywords: list) -> bool:
    """检测图像中是否包含任意一个关键词"""
    text = _rapid_ocr_text(img)
    for kw in keywords:
        if kw in text:
            log(f"RapidOCR 匹配OK: '{kw}' (从候选: {keywords})", verbose=True)
            return True
    log(f"RapidOCR 全部未匹配: {keywords}", verbose=True)
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
    适用于 OCR 无法识别的蓝色按钮上的文字。
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

    # 只处理前 10 个最大的候选区域，避免小噪点拖慢速度
    candidates = candidates[:10]
    log(f"蓝色区域检测: 找到 {len(candidates)} 个候选按钮", verbose=True)

    # 用 RapidOCR 识别每个候选区域
    fallback = None
    for idx, (x, y, bw, bh, area) in enumerate(candidates):
        roi = img[y:y + bh, x:x + bw]
        items = _rapid_ocr(roi)
        text = " ".join(item["text"] for item in items)
        if text:
            log(f"[{idx+1}/{len(candidates)}] ({x},{y}) {bw}x{bh} → '{text}'", verbose=True)
        for kw in target_keywords:
            if kw in text:
                cx, cy = x + bw // 2, y + bh // 2
                if len(text) <= len(kw) + 2:
                    log(f"蓝色按钮RapidOCR 精确OK: '{kw}' in '{text}' at ({cx},{cy})", verbose=True)
                    return (cx, cy)
                if fallback is None:
                    fallback = (cx, cy, kw, text)
                break
    if fallback:
        cx, cy, kw, text = fallback
        log(f"蓝色按钮RapidOCR 宽松OK: '{kw}' in '{text}' at ({cx},{cy})", verbose=True)
        return (cx, cy)
    log(f"蓝色区域检测: {len(candidates)} 个候选，均未匹配 {target_keywords}", verbose=True)
    return None


def find_blue_button_in_screenshot(keywords: list, save_name: str = "debug"):
    """截图并用蓝色区域检测查找按钮文字，返回中心坐标或 None"""
    img = take_screenshot()
    save_debug_screenshot(img, save_name)
    return find_blue_button_text(img, keywords)


# ============================================================
# 鼠标操作
# ============================================================

def _send_mouse_click(x: int, y: int):
    """通过 SendInput 移动鼠标并点击（兼容 DirectInput 游戏）
    坐标为屏幕绝对坐标。SendInput 的绝对坐标范围是 0-65535。
    """
    extra = ctypes.c_ulong(0)
    cx_screen = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    cy_screen = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    # 归一化到 0-65535
    nx = int(x * 65535 / cx_screen)
    ny = int(y * 65535 / cy_screen)

    def _mouse_event(flags, data=0):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.input.mi.dx = nx
        inp.input.mi.dy = ny
        inp.input.mi.mouseData = data
        inp.input.mi.dwFlags = flags
        inp.input.mi.time = 0
        inp.input.mi.dwExtraInfo = ctypes.pointer(extra)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    # 移动 + 左键按下 + 左键抬起
    _mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    time.sleep(0.03)
    _mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.05)
    _mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP)


def _send_mouse_move(x: int, y: int):
    """通过 SendInput 仅移动鼠标（不点击），兼容 DirectInput 游戏"""
    extra = ctypes.c_ulong(0)
    cx_screen = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    cy_screen = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    nx = int(x * 65535 / cx_screen)
    ny = int(y * 65535 / cy_screen)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.input.mi.dx = nx
    inp.input.mi.dy = ny
    inp.input.mi.mouseData = 0
    inp.input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    inp.input.mi.time = 0
    inp.input.mi.dwExtraInfo = ctypes.pointer(extra)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def click_position(x: int, y: int, duration: float = 0.2):
    """移动鼠标到指定位置并点击（使用 SendInput 底层 API，兼容 DirectInput 游戏）"""
    log(f"移动鼠标到 ({x}, {y}) 并点击", verbose=True)
    # 先用 pyautogui 平滑移动（让玩家能看到光标）
    try:
        pyautogui.moveTo(x, y, duration=duration)
    except Exception:
        pass
    time.sleep(0.05)
    # 用 SendInput 底层 API 点击（兼容 DirectInput 游戏）
    _send_mouse_click(x, y)


# ============================================================
# Windows 底层输入 (兼容 DirectInput 游戏)
# ============================================================

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
WHEEL_DELTA = 900  # 每个滚轮刻度

# 虚拟屏幕尺寸 (用于 SendInput 绝对坐标归一化)
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


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
    log(f"滚轮向下翻 {pages} 页 (scroll={scroll_val})", verbose=True)
    _send_mouse_wheel(scroll_val)


def scroll_notches(count: int):
    """按指定刻度数滚动（正=向下，负=向上）"""
    scroll_val = -WHEEL_DELTA * count
    _send_mouse_wheel(scroll_val)


def scroll_up(pages: int = 1):
    """控制滚轮向上翻页"""
    scroll_val = WHEEL_DELTA * 5 * pages
    log(f"滚轮向上翻 {pages} 页 (scroll={scroll_val})", verbose=True)
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
    log(f"按下按键: {key}", verbose=True)

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
        log(f"  -> SendInput 成功", verbose=True)
        return

    # 方法 2: SendInput 失败，用 PostMessage
    if hwnd:
        log(f"  -> SendInput 失败，改用 PostMessage", verbose=True)
        _send_postmessage_key(hwnd, vk, scan)
    else:
        log(f"  -> 未找到游戏窗口，尝试 pyautogui", verbose=True)
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


# 地标映射：OCR 无法识别的目的地 → 用相邻可识别目的地定位
# target: [(landmark_name, y_offset_in_items), ...]  负数=上方，按优先级排列
DESTINATION_LANDMARKS = {
    "天坠魔窟": [("天阳乡浮岛", -1), ("世界树地下都市遗址", -2)],
}

# 所有可选目的地（含"无"）
ALL_DESTINATIONS_WITH_NONE = ["（无）"] + DESTINATIONS_PAGE1 + DESTINATIONS_PAGE2

# ============================================================
# 核心自动化逻辑
# ============================================================

class AutoExpedition:
    def __init__(self):
        self.running = False
        self._lock = threading.Lock()
        self.destination = "草原的洞穴"  # 默认目的地
        self.multi_mode = False          # 是否多选模式
        self.multi_destinations = []     # 多选目的地列表
        self.original_time = None
        self._real_time = None           # 真实时间（用于最后恢复）
        self.auto_restart = False        # 流程失败后自动重启
        self._user_stopped = False       # 是否是用户手动停止

    def _restore_real_time(self):
        """恢复到当前真实时间（补偿期间经过的时间）"""
        if self._real_time:
            elapsed = time.monotonic() - self._step8_mono
            real_now = adjust_time(self._real_time, elapsed)
            if set_system_time(real_now):
                log(f"已恢复真实时间: {format_time(real_now)} (经过 {elapsed:.1f}s)")
            else:
                log("恢复真实时间失败！请手动调整")
            self._real_time = None

    def set_destination(self, dest: str):
        self.destination = dest

    def set_multi_destinations(self, dests: list):
        """设置多选目的地列表（已过滤掉 None）"""
        self.multi_destinations = [d for d in dests if d]

    def start(self):
        """启动自动化流程"""
        if not self._lock.acquire(blocking=False):
            log("已在运行中，忽略重复触发")
            return
        self.running = True
        log("=" * 50)
        if self.multi_mode and self.multi_destinations:
            log(f"启动自动化流程（多选模式），目的地队列: {' → '.join(self.multi_destinations)}")
        else:
            log(f"启动自动化流程，目的地: {self.destination}")
        log("=" * 50)
        threading.Thread(target=self._run_loop, daemon=True).start()

    def stop(self):
        """停止自动化流程（用户主动调用）"""
        self._user_stopped = True
        self.running = False
        log("已请求停止，等待当前循环结束...")

    def _run_loop(self):
        """主循环：重复执行远征流程"""
        try:
            # 多选模式：按队列顺序循环执行
            if self.multi_mode and self.multi_destinations:
                round_num = 0
                while self.running:
                    round_num += 1
                    log(f"[多选] ====== 第 {round_num} 轮 ======")
                    for i, dest in enumerate(self.multi_destinations):
                        if not self.running:
                            break
                        self.destination = dest
                        log(f"[多选] 第 {i+1}/{len(self.multi_destinations)} 个目的地: {dest}")
                        success = self._run_once()
                        if not self.running:
                            break
                        if not success:
                            log(f"[多选] 目的地 '{dest}' 失败，停止运行")
                            self.running = False
                            break
                        if i < len(self.multi_destinations) - 1:
                            log(f"[多选] '{dest}' 完成，准备下一个...")
                            time.sleep(0.5)
                    if self.running:
                        log(f"[多选] 第 {round_num} 轮全部完成，开始下一轮...")
                        time.sleep(0.5)
            else:
                # 单选模式：循环执行同一目的地
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
            should_restart = (
                self.auto_restart
                and not self._user_stopped  # 非用户手动停止
            )
            self.running = False
            self._lock.release()
            if should_restart:
                log("自动化流程异常结束，自动重启中...")
                time.sleep(3)
                self._user_stopped = False
                self.start()
            else:
                log("自动化流程已结束")

    def _run_once(self) -> bool:
        """执行一次完整的远征流程，返回是否成功"""
        self.original_time = None
        self._real_time = None
        self._step8_mono = 0
        self._rollback_mono = 0
        try:
            return self._run_once_inner()
        finally:
            # 无论成功还是失败，都确保恢复到真实时间
            if self.original_time:
                elapsed = time.monotonic() - self._rollback_mono
                restored = adjust_time(self.original_time, elapsed)
                if set_system_time(restored):
                    log(f"[安全恢复] 已恢复至: {format_time(restored)} (补偿 {elapsed:.3f}s)")
                else:
                    log("[安全恢复] 恢复时间失败！请手动调整")
                self.original_time = None
            if self._real_time:
                self._restore_real_time()

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
            # 可能是F键没有正确输入，检查是否有"打开"提示
            OPEN_KEYWORDS = ["打开", "交互", "调查"]
            if contains_any_text(img, OPEN_KEYWORDS):
                log("检测到'打开'提示，F键可能未生效，重新按下F...")
                time.sleep(0.3)
                press_key("f")
                time.sleep(DELAYS["detection_retry"] * 2)
                img = take_screenshot()
                if not contains_any_text(img, EXPEDITION_KEYWORDS):
                    log("重新按F后仍未检测到远征界面，停止运行")
                    return False
            else:
                log(f"第一次未检测到远征界面，等待 {DELAYS['detection_retry']*2}s 后重试...")
                time.sleep(DELAYS["detection_retry"] * 2)
                img2 = take_screenshot()
                if not contains_any_text(img2, EXPEDITION_KEYWORDS):
                    log("第二次仍未检测到远征界面，停止运行")
                    return False

        # ---- 步骤 5：检测派遣界面 ----
        DISPATCH_KEYWORDS = ["请选择派遣帕鲁远征的目的地", "派遣帕鲁远征", "选择目的", "目的地"]
        log("[步骤5] 检测派遣界面")
        img = take_screenshot()

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
        AUTO_KEYWORDS = ["自动指派", "自动指泊", "自动指"]
        pos = find_blue_button_in_screenshot(AUTO_KEYWORDS, "step7")
        if pos:
            click_position(pos[0], pos[1])
        else:
            log("蓝色按钮检测未找到，用全图OCR+行拼接匹配...")
            time.sleep(DELAYS["detection_retry"])
            img = take_screenshot()
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
        if contains_any_text(img, ["派遣帕鲁", "选择帕鲁", "帕鲁"]):
            log("检测到派遣帕鲁界面，等待自动指派完成...")
            # 自动指派已点过，等几秒让它自动选完帕鲁
            time.sleep(2.0)

        # ---- 步骤 8：回拨系统时间 1 小时 ----
        log(f"[步骤8] 等待 {DELAYS['pre_action']}s 后回拨系统时间 1 小时")
        time.sleep(DELAYS["pre_action"])
        self._real_time = get_system_time()  # 保存真实时间
        self._step8_mono = time.monotonic()  # 记录单调时钟
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
            pos = find_any_text_position(img, START_KEYWORDS)

        if not pos:
            log("第一次未找到 '开始'，重试...")
            time.sleep(DELAYS["detection_retry"])
            pos = find_blue_button_in_screenshot(START_KEYWORDS, "step9_retry")
            if not pos:
                img = take_screenshot()
                pos = find_any_text_position(img, START_KEYWORDS)
            if not pos:
                log("第二次仍未找到 '开始'，停止运行")
                return False
        click_position(pos[0], pos[1])

        # ---- 步骤 9.5：恢复系统时间 → 远征才会结束 ----
        # Palworld 远征机制：回拨时间后点开始，恢复时间时游戏发现时间已到 → 远征完成
        # 如果恢复后仍显示"远征中"，说明回拨不够，再回拨1小时再恢复
        log("[步骤9.5] 等待游戏记录开始时间...")
        time.sleep(1.0)

        expedition_done = False
        max_attempts = 5  # 最多往后推5次（5小时，足够任何远征）

        for attempt in range(1, max_attempts + 1):
            # 恢复/推进系统时间
            if attempt == 1:
                # 第一次：恢复到真实时间
                if self.original_time:
                    elapsed = time.monotonic() - self._rollback_mono
                    restored = adjust_time(self.original_time, elapsed)
                    if set_system_time(restored):
                        log(f"[尝试{attempt}] 恢复时间至: {format_time(restored)}")
                    else:
                        log("恢复时间失败！请手动调整")
                    self.original_time = None
            else:
                # 后续：往后推1小时
                current = get_system_time()
                pushed = adjust_time(current, 3600)  # +1小时
                if set_system_time(pushed):
                    log(f"[尝试{attempt}] 时间往后推1小时至: {format_time(pushed)}")
                else:
                    log("推进时间失败！")

            # 等待游戏响应
            time.sleep(2.0)

            # 检测结果
            img = take_screenshot()

            # 情况1: 远征完成 → 恢复真实时间，进入步骤10
            if contains_any_text(img, ["物品栏", "领取", "奖励", "完成"]):
                log(f"远征完成！（第{attempt}次尝试后）")
                # 恢复到真实时间
                self._restore_real_time()
                expedition_done = True
                break

            # 情况2: 仍在远征中 → 下次循环再往后推1小时
            if contains_any_text(img, ["远征中", "剩余时间", "远征"]):
                log(f"仍在远征中，下次往后推1小时...")
            else:
                log(f"未检测到明确状态，等待后重试...")

        if not expedition_done:
            # 恢复真实时间
            self._restore_real_time()
            log("多次尝试后仍未确认远征完成，继续尝试领取...")

        # ---- 步骤 10-12：按F → 检测物品栏 → 没找到再按一次F，两次都没有直接按X ----
        menu_opened = False
        for f_attempt in range(2):
            wait_t = 0.5 if f_attempt == 0 else DELAYS["detection_retry"]
            log(f"[步骤10] 等待 {wait_t:.1f}s 后按下 F 键 (第{f_attempt + 1}次)")
            time.sleep(wait_t)
            press_key("f")
            time.sleep(DELAYS["step12_detect_wait"])
            img = take_screenshot()
            if contains_any_text(img, ["物品栏"]):
                log("检测到物品栏")
                menu_opened = True
                break
            log(f"第{f_attempt + 1}次F后未检测到 '物品栏'，重试...")

        if not menu_opened:
            log("2次按F后仍未检测到物品栏，直接按X取奖励")

        # 按 X 取走全部奖励
        log("按下 X 取走全部奖励")
        press_key("x")
        time.sleep(DELAYS["step12_reward_wait"])

        # 按 ESC 关闭菜单
        log("按下 ESC 关闭菜单")
        press_key("escape")
        time.sleep(DELAYS["step12_close_wait"])

        log("本次远征流程完成 [OK]")
        return True

    def _step6_select_destination(self) -> bool:
        """步骤6：选择目的地
        第一页：直接截图识别，移动鼠标到文字位置点击
        第二页：滚动一页→500ms→截图识别→没找到检查是否有第一页文字→
               有则说明滚动没生效，再截图验证一次→还没有就停止
        """
        dest = self.destination

        screen_w, screen_h = pyautogui.size()
        list_x, list_y = screen_w // 2, screen_h // 2

        def _move_and_scroll(notches):
            """只移动鼠标到列表中心（不点击），然后滚动"""
            _send_mouse_move(list_x, list_y)
            time.sleep(0.1)
            log(f"滚动 {notches} 格", verbose=True)
            scroll_notches(notches)
            time.sleep(0.5)  # 等500ms让列表滚动到位

        def _try_find():
            """截图识别目标文字，返回中心坐标或None"""
            img = take_screenshot()
            # 先精确查找
            pos = find_text_fuzzy_center(img, dest)
            if pos:
                return pos
            # 地标法回退
            pos = _find_by_landmark(img, dest)
            if pos:
                return pos
            return None

        def _check_page1_visible(img):
            """检查截图中是否有第一页的目的地文字（说明还在第一页）"""
            page1_names = ["草原的洞穴", "森林的秘境", "火山的灼热洞穴",
                           "沙漠的隐秘遗迹", "雪山的冻结洞穴", "樱花岛的灵花洞穴"]
            return contains_any_text(img, page1_names)

        # ---- 第一页目的地：直接识别 ----
        if dest not in DESTINATIONS_PAGE2:
            log(f"目的地 '{dest}'（第一页），直接识别...")
            pos = _try_find()
            if pos:
                click_position(pos[0], pos[1])
                return True
            # 第一页没找到，再截图验证一次
            log("第一次未找到，重新截图验证...")
            time.sleep(0.5)
            pos = _try_find()
            if pos:
                click_position(pos[0], pos[1])
                return True
            log(f"未找到目的地 '{dest}'，停止运行")
            return False

        # ---- 第二页目的地：滚动一次后识别 ----
        log(f"目的地 '{dest}'（第二页），向下滚动一页...")
        _move_and_scroll(1)

        # 第1次尝试：滚动后直接识别
        pos = _try_find()
        if pos:
            click_position(pos[0], pos[1])
            return True

        # 没找到 → 检查有没有第一页的文字（草原的洞穴等）
        log("未找到目标，检查是否仍在第一页...")
        img = take_screenshot()
        if _check_page1_visible(img):
            # 看到了第一页文字，说明滚动没生效，再截图验证一次
            log("检测到第一页文字，滚动可能未生效，再截图验证...")
            time.sleep(0.5)
            pos = _try_find()
            if pos:
                click_position(pos[0], pos[1])
                return True
            log(f"验证后仍未找到 '{dest}'，停止运行")
            return False
        else:
            # 没看到第一页文字，可能在中间位置，再截图验证一次
            log("未检测到第一页文字，再截图验证...")
            time.sleep(0.5)
            pos = _try_find()
            if pos:
                click_position(pos[0], pos[1])
                return True
            log(f"未找到目的地 '{dest}'，停止运行")
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
        self.root.geometry("800x900")
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
        combo_values = all_destinations + ["多选"]
        self.dest_var = tk.StringVar(value=all_destinations[0])
        dest_combo = ttk.Combobox(
            frame_top, textvariable=self.dest_var,
            values=combo_values, state="readonly", width=25
        )
        dest_combo.pack(side="left", padx=10)
        dest_combo.bind("<<ComboboxSelected>>", self._on_dest_change)

        # 多选设置按钮（默认隐藏）
        self.multi_btn = ttk.Button(frame_top, text="多选设置", command=self._open_multi_settings)
        # 初始状态：如果配置已保存了多选模式，显示按钮
        if self.dest_var.get() == "多选":
            self.multi_btn.pack(side="left", padx=5)

        # 多选状态标签（第二行）
        self.multi_status_label = ttk.Label(frame_top, text="", foreground="blue")
        self.multi_status_label.pack(anchor="w", padx=(0, 0), pady=(3, 0))
        self._update_multi_status()

        # ---- 中部：控制按钮 ----
        frame_mid = ttk.LabelFrame(self.root, text="控制", padding=10)
        frame_mid.pack(fill="x", padx=10, pady=5)

        self.btn_start = ttk.Button(frame_mid, text="开始", command=self._toggle)
        self.btn_start.pack(side="left", padx=5)

        ttk.Button(frame_mid, text="停止", command=self._stop).pack(side="left", padx=5)

        # 自动重启勾选框
        self.auto_restart_var = tk.BooleanVar(value=False)
        self.auto_restart_cb = ttk.Checkbutton(
            frame_mid, text="失败后自动重启", variable=self.auto_restart_var,
            command=self._on_auto_restart_change
        )
        self.auto_restart_cb.pack(side="left", padx=15)

        self.hotkey_btn = ttk.Button(
            frame_mid, text=f"热键: {_key_to_display(HOTKEY)}",
            command=self._start_bind_hotkey, width=16
        )
        self.hotkey_btn.pack(side="left", padx=15)

        self.status_label = ttk.Label(frame_mid, text="状态: 就绪", foreground="gray")
        self.status_label.pack(side="right", padx=10)

        # ---- RapidOCR 状态 ----
        frame_ocr = ttk.LabelFrame(self.root, text="OCR 引擎", padding=10)
        frame_ocr.pack(fill="x", padx=10, pady=5)

        self.ocr_status_label = ttk.Label(frame_ocr, text=f"RapidOCR ({_ocr_backend})", foreground="green")
        self.ocr_status_label.pack(side="left")

        # GPU/CPU 切换按钮（仅在 DirectML 可用时显示）
        if _DML_AVAILABLE:
            self.ocr_mode_var = tk.StringVar(value="GPU" if _ocr_use_gpu else "CPU")
            ocr_combo = ttk.Combobox(
                frame_ocr, textvariable=self.ocr_mode_var,
                values=["GPU", "CPU"], state="readonly", width=6
            )
            ocr_combo.pack(side="left", padx=10)
            ocr_combo.bind("<<ComboboxSelected>>", self._on_ocr_mode_change)
        else:
            ttk.Label(frame_ocr, text="(DirectML 不可用，仅 CPU)", foreground="gray").pack(side="left", padx=10)

        # ---- 缓存管理 ----
        frame_cache = ttk.LabelFrame(self.root, text="缓存管理", padding=10)
        frame_cache.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_cache, text=f"配置目录: {CONFIG_DIR}", foreground="gray").pack(anchor="w")

        cache_sub = ttk.Frame(frame_cache)
        cache_sub.pack(fill="x", pady=2)
        self.cache_label = ttk.Label(cache_sub, text="截图缓存: 计算中...")
        self.cache_label.pack(side="left")
        ttk.Button(cache_sub, text="刷新", command=self._refresh_cache_size).pack(side="left", padx=10)
        ttk.Button(cache_sub, text="清除缓存", command=self._clear_cache).pack(side="left", padx=5)

        log_sub = ttk.Frame(frame_cache)
        log_sub.pack(fill="x", pady=2)
        self.log_size_label = ttk.Label(log_sub, text="日志文件: 计算中...")
        self.log_size_label.pack(side="left")
        ttk.Button(log_sub, text="打开日志目录", command=lambda: os.startfile(os.path.abspath(LOG_DIR))).pack(side="left", padx=10)

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
        if dest == "多选":
            self.multi_btn.pack(side="left", padx=5)
            self._update_multi_status()
            log("已切换到多选模式")
        else:
            self.multi_btn.pack_forget()
            self.multi_status_label.config(text="")
            _expedition.multi_mode = False
            _expedition.set_destination(dest)
            log(f"目的地已切换为: {dest}")

    def _update_multi_status(self):
        """更新多选状态标签"""
        active = [d for d in MULTI_DESTINATIONS if d]
        if active:
            display = " → ".join(active)
            self.multi_status_label.config(text=f"队列: {display}", foreground="blue")
        else:
            self.multi_status_label.config(text="队列: [未设置]", foreground="gray")

    def _open_multi_settings(self):
        """打开多选设置弹窗"""
        win = tk.Toplevel(self.root)
        win.title("多选目的地设置")
        win.resizable(False, False)
        win.grab_set()  # 模态窗口

        ttk.Label(win, text='设置远征目的地执行顺序(留空或选(无)表示跳过):',
                  font=("", 9)).pack(padx=15, pady=(15, 5))

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="x", padx=10)

        all_values = ["（无）"] + DESTINATIONS_PAGE1 + DESTINATIONS_PAGE2
        combos = []

        for i in range(6):
            row_frame = ttk.Frame(frame)
            row_frame.pack(fill="x", pady=3)
            ttk.Label(row_frame, text=f"第 {i+1} 个:", width=8).pack(side="left")

            # 当前值：从 MULTI_DESTINATIONS 读取
            current = MULTI_DESTINATIONS[i] if MULTI_DESTINATIONS[i] else "（无）"
            var = tk.StringVar(value=current)
            combo = ttk.Combobox(row_frame, textvariable=var,
                                values=all_values, state="readonly", width=25)
            combo.pack(side="left", padx=5)
            combos.append(var)

        def _apply():
            for i in range(6):
                val = combos[i].get()
                MULTI_DESTINATIONS[i] = None if val == "（无）" else val
            save_delays_config()
            self._update_multi_status()
            active = [d for d in MULTI_DESTINATIONS if d]
            log(f"多选目的地已更新: {' → '.join(active) if active else '（空）'}")
            win.destroy()

        btn_frame = ttk.Frame(win, padding=10)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="确定", command=_apply).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="取消", command=win.destroy).pack(side="right", padx=5)

        # 居中显示
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

    def _toggle(self):
        """切换开始/停止"""
        if _expedition.running:
            self._stop()
        else:
            self._start()

    def _on_auto_restart_change(self):
        """自动重启勾选框变更"""
        _expedition.auto_restart = self.auto_restart_var.get()
        _expedition._user_stopped = False
        status = "开启" if _expedition.auto_restart else "关闭"
        log(f"失败后自动重启: {status}")

    def _on_ocr_mode_change(self, event=None):
        """OCR GPU/CPU 切换"""
        use_gpu = self.ocr_mode_var.get() == "GPU"
        _init_ocr_engine(use_gpu=use_gpu)
        self.ocr_status_label.config(text=f"RapidOCR ({_ocr_backend})")

    def _start(self):
        """开始"""
        _expedition._user_stopped = False  # 每次启动时重置
        dest = self.dest_var.get()
        if dest == "多选":
            # 多选模式
            active = [d for d in MULTI_DESTINATIONS if d]
            if not active:
                log('多选模式下未设置任何目的地，请先点击"多选设置"配置')
                return
            _expedition.multi_mode = True
            _expedition.set_multi_destinations(active)
        else:
            # 单选模式
            _expedition.multi_mode = False
            _expedition.set_destination(dest)
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
        """刷新缓存大小和日志文件大小显示"""
        total, count = self._get_cache_size()
        self.cache_label.config(text=f"截图缓存: {count} 个文件, {self._format_size(total)}")
        # 日志文件大小
        log_total = 0
        log_count = 0
        if os.path.isdir(LOG_DIR):
            for f in os.listdir(LOG_DIR):
                fp = os.path.join(LOG_DIR, f)
                if os.path.isfile(fp) and f.endswith(".log"):
                    log_total += os.path.getsize(fp)
                    log_count += 1
        self.log_size_label.config(text=f"日志: {log_count} 个文件, {self._format_size(log_total)}")

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

    # 管理员权限检测
    _is_admin = False
    try:
        _is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        pass
    if not _is_admin:
        print("  [!] 警告: 未以管理员权限运行!")
        print("  [!] 游戏如果是管理员运行的, SendInput 鼠标/滚轮将无法工作")
        print("  [!] 请右键以管理员身份运行此程序")
        print()
    else:
        print("  [OK] 已以管理员权限运行")

    print(f"  日志文件: {_log_file_path}")
    print(f"  OCR 引擎: RapidOCR ({_ocr_backend})")
    print(f"  RapidOCR 引擎首次加载较慢（约5-10秒），属正常现象")
    print("=" * 50)
    print()

    # 写入会话开始日志
    log(f"===== 会话开始 =====")
    log(f"版本: {VERSION}")
    log(f"OCR 引擎: RapidOCR ({_ocr_backend})")
    log(f"DirectML 可用: {_DML_AVAILABLE}")
    log(f"管理员权限: {_is_admin}")
    log(f"配置目录: {CONFIG_DIR}")

    app = App()
    try:
        app.run()
    finally:
        log("===== 会话结束 =====")
        # 关闭日志文件
        if _log_file:
            try:
                _log_file.close()
            except Exception:
                pass
