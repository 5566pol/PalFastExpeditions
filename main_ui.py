"""
PalFastExpeditions UI - CustomTkinter 主题自适应界面
侧边栏导航：自动远征 / 自动竞技场 / 全局设置
支持主题切换：跟随系统 / 浅色 / 深色
"""

import customtkinter as ctk
from tkinter import messagebox
import tkinter as tk
import os

# ============================================================
# 主题配置
# ============================================================

ctk.set_default_color_theme("blue")

# 主题模式顺序：system → light → dark → system
_THEME_CYCLE = ["system", "light", "dark"]
_THEME_ICONS = {"system": "💻", "light": "☀️", "dark": "🌙"}
_THEME_LABELS = {"system": "跟随系统", "light": "浅色模式", "dark": "深色模式"}

# 语义化颜色方案（深色 / 浅色自适应）
_SCHEMES = {
    "dark": {
        "sidebar_bg":      "#1a1a2e",
        "sidebar_active":  "#16213e",
        "sidebar_hover":   "#0f3460",
        "sidebar_sep":     "#3d3d5c",
        "accent":          "#e94560",
        "success":         "#00b894",
        "success_hover":   "#00a884",
        "warning":         "#fdcb6e",
        "danger":          "#e94560",
        "danger_hover":    "#c0392b",
        "text":            "#ecf0f1",
        "text_dim":        "#7f8c8d",
        "card_bg":         "#2d2d44",
        "log_bg":          "#1e1e2e",
        "sep":             "#3d3d5c",
        "btn_ctrl_fg":     "#636e72",
        "btn_ctrl_hover":  "#2d3436",
    },
    "light": {
        "sidebar_bg":      "#f0f0f5",
        "sidebar_active":  "#dce4f0",
        "sidebar_hover":   "#cdd8ea",
        "sidebar_sep":     "#c0c0d0",
        "accent":          "#e94560",
        "success":         "#00b894",
        "success_hover":   "#009b7a",
        "warning":         "#fdcb6e",
        "danger":          "#e94560",
        "danger_hover":    "#c0392b",
        "text":            "#2d3436",
        "text_dim":        "#636e72",
        "card_bg":         "#ffffff",
        "log_bg":          "#f8f8fc",
        "sep":             "#d0d0dc",
        "btn_ctrl_fg":     "#b0b8c4",
        "btn_ctrl_hover":  "#a0a8b4",
    },
}

# 全局引用，随主题切换更新
C = dict(_SCHEMES["dark"])


def _resolve_appearance_mode(mode: str) -> str:
    """将 system 解析为实际的 dark/light"""
    if mode in ("dark", "light"):
        return mode
    try:
        import darkdetect
        return darkdetect.theme().lower()
    except Exception:
        return "dark"


def _update_colors(mode: str):
    """根据当前模式刷新全局颜色"""
    global C
    resolved = _resolve_appearance_mode(mode)
    C.update(_SCHEMES[resolved])


class App:
    """主应用窗口 - 侧边栏导航布局"""

    def __init__(self, config: dict):
        """
        config: 从 main.py 传入的配置字典，包含:
            - version: str
            - hotkey_display: str
            - arena_hotkey_display: str
            - ocr_backend: str
            - ocr_use_gpu: bool
            - dml_available: bool
            - game_running: bool
            - destinations_page1: list
            - destinations_page2: list
            - current_destination: str
            - multi_destinations: list[6]
            - delays: dict
            - delay_labels: dict
            - default_delays: dict
            - arena_pal_main: str
            - arena_pal_sub1: str
            - arena_pal_sub2: str
            - arena_tier: str
            - arena_battle_time: float
            - tiers: list
            - pal_names: list
            - config_dir: str
            - log_dir: str
        """
        self.config = config
        self._current_page = "expedition"

        # 加载保存的主题，默认跟随系统
        saved_theme = config.get("theme", "system")
        self._current_theme = saved_theme if saved_theme in _THEME_CYCLE else "system"
        ctk.set_appearance_mode(self._current_theme)
        _update_colors(self._current_theme)

        # 回调函数（由 main.py 注册）
        self.on_start_expedition = None
        self.on_stop_expedition = None
        self.on_start_arena = None
        self.on_stop_arena = None
        self.on_save_delays = None
        self.on_reset_delays = None
        self.on_save_arena_config = None
        self.on_bind_hotkey = None
        self.on_bind_arena_hotkey = None
        self.on_bind_fishing_hotkey = None
        self.on_ocr_mode_change = None
        self.on_clear_cache = None
        self.on_dest_change = None
        self.on_auto_restart_change = None
        self.on_theme_change = None
        self.on_check_update = None
        self.on_start_fishing = None
        self.on_stop_fishing = None

        self._build_window()
        self._build_sidebar()
        self._build_pages()
        self._show_page("expedition")

    # ================================================================
    # 窗口基础
    # ================================================================

    def _build_window(self):
        self.root = ctk.CTk()
        self.root.title(f"PalFastExpeditions {self.config['version']}")
        self.root.geometry("900x750")
        self.root.minsize(800, 650)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 主容器：左侧边栏 + 右侧内容
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

    def _on_close(self):
        self.root.quit()
        self.root.destroy()

    # ================================================================
    # 侧边栏
    # ================================================================

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self.root, width=180, corner_radius=0,
                               fg_color=C["sidebar_bg"])
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        self._sidebar = sidebar

        # Logo 区域
        self._logo_label = ctk.CTkLabel(sidebar, text="⚡ PalFastExpeditions",
                                   font=ctk.CTkFont(size=22, weight="bold"),
                                   text_color=C["accent"])
        self._logo_label.pack(pady=(25, 5), padx=15, anchor="w")

        self._ver_label = ctk.CTkLabel(sidebar, text=self.config["version"],
                                  font=ctk.CTkFont(size=11),
                                  text_color=C["text_dim"])
        self._ver_label.pack(padx=15, anchor="w")

        # 分隔线
        self._sidebar_seps = []
        sep = ctk.CTkFrame(sidebar, height=1, fg_color=C["sidebar_sep"])
        sep.pack(fill="x", padx=15, pady=20)
        self._sidebar_seps.append(sep)

        # 导航按钮
        self._nav_buttons = {}
        nav_items = [
            ("expedition", "自动远征"),
            ("arena",      "自动竞技场"),
            # ("fishing",    "自动钓鱼"),  # TODO: 暂时禁用
            ("settings",   "全局设置"),
        ]
        for page_id, label in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w",
                font=ctk.CTkFont(size=14),
                fg_color="transparent", hover_color=C["sidebar_hover"],
                height=40, corner_radius=8,
                command=lambda p=page_id: self._show_page(p),
            )
            btn.pack(fill="x", padx=10, pady=3)
            self._nav_buttons[page_id] = btn

        # 底部状态
        bottom_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom_frame.pack(side="bottom", fill="x", padx=10, pady=15)

        # 分隔线
        sep2 = ctk.CTkFrame(bottom_frame, height=1, fg_color=C["sidebar_sep"])
        sep2.pack(fill="x", pady=(0, 8))
        self._sidebar_seps.append(sep2)

        self.game_status_label = ctk.CTkLabel(
            bottom_frame, text="🔴 游戏未运行",
            font=ctk.CTkFont(size=12), text_color=C["danger"],
            anchor="w",
        )
        self.game_status_label.pack(fill="x", pady=2)

        self.ocr_status_label = ctk.CTkLabel(
            bottom_frame,
            text=f"OCR: {self.config['ocr_backend']}",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
            anchor="w",
        )
        self.ocr_status_label.pack(fill="x", pady=2)

    def _show_page(self, page_id: str):
        self._current_page = page_id
        # 更新按钮样式
        for pid, btn in self._nav_buttons.items():
            if pid == page_id:
                btn.configure(fg_color=C["sidebar_active"], text_color=C["text"])
            else:
                btn.configure(fg_color="transparent", text_color=C["text_dim"])
        # 切换页面
        for pid, frame in self._page_frames.items():
            if pid == page_id:
                frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
            else:
                frame.grid_forget()

    # ================================================================
    # 页面容器
    # ================================================================

    def _build_pages(self):
        self._page_frames = {}
        self._page_frames["expedition"] = self._build_expedition_page()
        self._page_frames["arena"] = self._build_arena_page()
        # self._page_frames["fishing"] = self._build_fishing_page()  # TODO: 暂时禁用
        self._page_frames["settings"] = self._build_settings_page()

    # ================================================================
    # 页面1: 自动远征
    # ================================================================

    def _build_expedition_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.root, fg_color="transparent")

        # 可滚动区域
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # ---- 目的地选择 ----
        card_dest = self._make_card(scroll, "🎯 目的地设置")

        row1 = ctk.CTkFrame(card_dest, fg_color="transparent")
        row1.pack(fill="x", pady=(5, 0))

        ctk.CTkLabel(row1, text="选择目的地:", font=ctk.CTkFont(size=13)).pack(side="left")

        all_dest = self.config["destinations_page1"] + self.config["destinations_page2"]
        combo_values = all_dest + ["多选模式"]
        self.dest_var = ctk.StringVar(value=self.config["current_destination"])
        dest_combo = ctk.CTkComboBox(
            row1, variable=self.dest_var, values=combo_values,
            width=220, state="readonly",
            command=self._on_dest_change_internal,
        )
        dest_combo.pack(side="left", padx=10)

        self.multi_btn = ctk.CTkButton(
            row1, text="📋 多选设置", width=100, height=30,
            fg_color="#6c5ce7", hover_color="#5b4cdb",
            command=self._open_multi_settings,
        )
        # 初始显示
        if self.dest_var.get() == "多选模式":
            self.multi_btn.pack(side="left", padx=5)

        self.multi_status = ctk.CTkLabel(
            card_dest, text="", font=ctk.CTkFont(size=12),
            text_color=C["accent"], anchor="w",
        )
        self.multi_status.pack(fill="x", pady=(5, 0))
        self._update_multi_status()

        # ---- 控制区 ----
        card_ctrl = self._make_card(scroll, "🎮 控制")

        ctrl_row = ctk.CTkFrame(card_ctrl, fg_color="transparent")
        ctrl_row.pack(fill="x", pady=5)

        self.btn_start = ctk.CTkButton(
            ctrl_row, text="▶ 开始", width=100, height=36,
            fg_color=C["success"], hover_color=C["success_hover"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._toggle_expedition,
        )
        self.btn_start.pack(side="left", padx=(0, 10))

        self.btn_stop = ctk.CTkButton(
            ctrl_row, text="⏹ 停止", width=100, height=36,
            fg_color=C["danger"], hover_color=C["danger_hover"],
            font=ctk.CTkFont(size=14),
            command=self._stop_expedition,
        )
        self.btn_stop.pack(side="left", padx=(0, 15))

        self.auto_restart_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            ctrl_row, text="失败自动重启", variable=self.auto_restart_var,
            font=ctk.CTkFont(size=12),
            command=self._on_auto_restart_change_internal,
        ).pack(side="left", padx=10)

        # 热键 + 状态
        info_row = ctk.CTkFrame(card_ctrl, fg_color="transparent")
        info_row.pack(fill="x", pady=(5, 0))

        self.hotkey_btn = ctk.CTkButton(
            info_row, text=f"🔘 热键: {self.config['hotkey_display']}",
            width=150, height=30, fg_color=C["btn_ctrl_fg"], hover_color=C["btn_ctrl_hover"],
            command=self._bind_hotkey,
        )
        self.hotkey_btn.pack(side="left")

        self.expedition_status = ctk.CTkLabel(
            info_row, text="⏸ 就绪", font=ctk.CTkFont(size=13),
            text_color=C["text_dim"],
        )
        self.expedition_status.pack(side="right")

        # ---- 日志区 ----
        card_log = self._make_card(scroll, "📝 运行日志", expand=True)

        self.log_text = ctk.CTkTextbox(
            card_log, height=200, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=C["log_bg"], text_color=C["text"],
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True, pady=(5, 0))
        self.log_text.configure(state="disabled")

        # 底部提示
        ctk.CTkLabel(
            scroll, text=f"按 {self.config['hotkey_display']} 开始/停止",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
        ).pack(pady=(5, 0))

        return page

    # ================================================================
    # 页面2: 自动竞技场
    # ================================================================

    def _build_arena_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.root, fg_color="transparent")

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # ---- 帕鲁选择 ----
        card_pal = self._make_card(scroll, "🐾 帕鲁选择")

        pal_names = self.config.get("pal_names", [])
        pal_fields = [
            ("主战帕鲁:", "arena_pal_main"),
            ("辅助帕鲁1:", "arena_pal_sub1"),
            ("辅助帕鲁2:", "arena_pal_sub2"),
        ]
        self.arena_pal_vars = {}
        for label_text, key in pal_fields:
            row = ctk.CTkFrame(card_pal, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label_text, width=90, anchor="w",
                         font=ctk.CTkFont(size=13)).pack(side="left")
            var = ctk.StringVar(value=self.config.get(key, ""))
            entry = ctk.CTkComboBox(row, variable=var, values=pal_names, width=200)
            entry.pack(side="left", padx=10)
            self.arena_pal_vars[key] = var

        hint = ctk.CTkLabel(card_pal, text="输入帕鲁编号或名称，如 5 / 冲浪鸭",
                             font=ctk.CTkFont(size=11), text_color=C["text_dim"])
        hint.pack(anchor="w", pady=(2, 0))

        # ---- 对手 & 战斗 ----
        card_battle = self._make_card(scroll, "⚔️ 对手设置")

        row_tier = ctk.CTkFrame(card_battle, fg_color="transparent")
        row_tier.pack(fill="x", pady=3)
        ctk.CTkLabel(row_tier, text="对手段位:", width=90, anchor="w",
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self.arena_tier_var = ctk.StringVar(value=self.config["arena_tier"])
        ctk.CTkComboBox(
            row_tier, variable=self.arena_tier_var,
            values=self.config["tiers"], width=120, state="readonly",
        ).pack(side="left", padx=10)

        row_time = ctk.CTkFrame(card_battle, fg_color="transparent")
        row_time.pack(fill="x", pady=3)
        ctk.CTkLabel(row_time, text="完战时间:", width=90, anchor="w",
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self.arena_battle_time_var = ctk.StringVar(value=str(self.config["arena_battle_time"]))
        ctk.CTkEntry(row_time, textvariable=self.arena_battle_time_var,
                     width=80).pack(side="left", padx=10)
        ctk.CTkLabel(row_time, text="秒 (含加载返回世界耗时)",
                     font=ctk.CTkFont(size=11), text_color=C["text_dim"]).pack(side="left")

        # ---- 控制 ----
        card_arena_ctrl = self._make_card(scroll, "🎮 控制")

        arow = ctk.CTkFrame(card_arena_ctrl, fg_color="transparent")
        arow.pack(fill="x", pady=5)

        self.btn_arena_start = ctk.CTkButton(
            arow, text="▶ 启动竞技场", width=130, height=36,
            fg_color=C["success"], hover_color=C["success_hover"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._toggle_arena,
        )
        self.btn_arena_start.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            arow, text="⏹ 停止", width=100, height=36,
            fg_color=C["danger"], hover_color=C["danger_hover"],
            command=self._stop_arena,
        ).pack(side="left", padx=(0, 15))

        self.arena_hotkey_btn = ctk.CTkButton(
            arow, text=f"🔘 热键: {self.config['arena_hotkey_display']}",
            width=150, height=30, fg_color=C["btn_ctrl_fg"], hover_color=C["btn_ctrl_hover"],
            command=self._bind_arena_hotkey,
        )
        self.arena_hotkey_btn.pack(side="left", padx=10)

        self.arena_status = ctk.CTkLabel(
            arow, text="⏸ 就绪", font=ctk.CTkFont(size=13),
            text_color=C["text_dim"],
        )
        self.arena_status.pack(side="right")

        # ---- 日志 ----
        card_arena_log = self._make_card(scroll, "📝 竞技场日志", expand=True)

        self.arena_log_text = ctk.CTkTextbox(
            card_arena_log, height=180, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=C["log_bg"], text_color=C["text"],
            wrap="word",
        )
        self.arena_log_text.pack(fill="both", expand=True, pady=(5, 0))
        self.arena_log_text.configure(state="disabled")

        ctk.CTkLabel(
            scroll, text=f"按 {self.config['arena_hotkey_display']} 开始/停止竞技场",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
        ).pack(pady=(5, 0))

        return page

    # ================================================================
    # 页面3: 自动钓鱼
    # ================================================================

    def _build_fishing_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.root, fg_color="transparent")

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # ---- 操作区 ----
        card_ctrl = self._make_card(scroll, "自动钓鱼")

        btn_row = ctk.CTkFrame(card_ctrl, fg_color="transparent")
        btn_row.pack(fill="x", pady=5)

        self.fishing_btn_start = ctk.CTkButton(
            btn_row, text="▶ 启动", width=130, height=36,
            fg_color=C["success"], hover_color=C["success_hover"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._toggle_fishing,
        )
        self.fishing_btn_start.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="⏹ 停止", width=100, height=36,
            fg_color=C["danger"], hover_color=C["danger_hover"],
            command=self._stop_fishing,
        ).pack(side="left", padx=(0, 8))

        self.fishing_hotkey_btn = ctk.CTkButton(
            btn_row, text=f"🔘 热键: {self.config['fishing_hotkey_display']}",
            width=150, height=30, fg_color=C["btn_ctrl_fg"], hover_color=C["btn_ctrl_hover"],
            command=self._bind_fishing_hotkey,
        )
        self.fishing_hotkey_btn.pack(side="left", padx=10)

        self.fishing_status = ctk.CTkLabel(
            btn_row, text="⏸ 就绪", font=ctk.CTkFont(size=13),
            text_color=C["text_dim"],
        )
        self.fishing_status.pack(side="right")

        # ---- 说明 ----
        ctk.CTkLabel(
            card_ctrl,
            text="自动检测咬钩（黄色感叹号）并点击，然后自动完成钓鱼小游戏。\n"
                 "请先手动抛竿，然后启动自动钓鱼。",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
            anchor="w", justify="left",
        ).pack(fill="x", pady=(5, 8))

        # ---- 日志 ----
        card_log = self._make_card(scroll, "钓鱼日志")

        self.fishing_log_text = ctk.CTkTextbox(
            card_log, height=200, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=C["log_bg"], text_color=C["text"],
        )
        self.fishing_log_text.pack(fill="both", expand=True, pady=(0, 8))
        self.fishing_log_text.configure(state="disabled")

        ctk.CTkLabel(
            scroll, text=f"按 {self.config['fishing_hotkey_display']} 开始/停止钓鱼",
            font=ctk.CTkFont(size=11), text_color=C["text_dim"],
        ).pack(pady=(5, 0))

        self._fishing_running = False
        return page

    def _toggle_fishing(self):
        if not self._fishing_running:
            if self.on_start_fishing:
                self.on_start_fishing()
                self._fishing_running = True
                self.fishing_btn_start.configure(text="⏸ 暂停")
        else:
            if self.on_stop_fishing:
                self.on_stop_fishing()
                self._fishing_running = False
                self.fishing_btn_start.configure(text="▶ 启动")

    def _stop_fishing(self):
        if self.on_stop_fishing:
            self.on_stop_fishing()
        self._fishing_running = False
        self.fishing_btn_start.configure(text="▶ 启动")

    def set_fishing_status(self, text, color=None):
        if color is None:
            color = C["text_dim"]
        self.fishing_status.configure(text=text, text_color=color)

    def append_fishing_log(self, msg: str):
        self.fishing_log_text.configure(state="normal")
        self.fishing_log_text.insert("end", msg + "\n")
        self.fishing_log_text.see("end")
        self.fishing_log_text.configure(state="disabled")

    # ================================================================
    # 页面4: 全局设置
    # ================================================================

    def _build_settings_page(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.root, fg_color="transparent")

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=10)

        # ---- OCR 引擎 ----
        card_ocr = self._make_card(scroll, "🔍 OCR 引擎")

        ocr_row = ctk.CTkFrame(card_ocr, fg_color="transparent")
        ocr_row.pack(fill="x", pady=5)

        ctk.CTkLabel(ocr_row, text=f"当前后端: {self.config['ocr_backend']}",
                     font=ctk.CTkFont(size=13)).pack(side="left")

        if self.config["dml_available"]:
            self.ocr_mode_var = ctk.StringVar(
                value="GPU" if self.config["ocr_use_gpu"] else "CPU"
            )
            ctk.CTkSegmentedButton(
                ocr_row, values=["GPU", "CPU"], variable=self.ocr_mode_var,
                command=self._on_ocr_mode_change_internal,
            ).pack(side="right")
        else:
            ctk.CTkLabel(ocr_row, text="DirectML 不可用，仅 CPU",
                         text_color=C["text_dim"]).pack(side="right")

        # ---- 延迟设置 ----
        card_delay = self._make_card(scroll, "⏱ 延迟设置 (秒)")

        self.delay_vars = {}
        delays = self.config["delays"]
        delay_labels = self.config["delay_labels"]
        keys = list(delay_labels.keys())

        grid_frame = ctk.CTkFrame(card_delay, fg_color="transparent")
        grid_frame.pack(fill="x", pady=5)

        cols = 3
        for i, key in enumerate(keys):
            row, col = divmod(i, cols)
            cell = ctk.CTkFrame(grid_frame, fg_color="transparent")
            cell.grid(row=row, column=col, padx=5, pady=4, sticky="w")
            ctk.CTkLabel(cell, text=f"{delay_labels[key]}:", width=110, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left")
            var = ctk.StringVar(value=str(delays[key]))
            ctk.CTkEntry(cell, textvariable=var, width=60,
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
            self.delay_vars[key] = var

        btn_row = ctk.CTkFrame(card_delay, fg_color="transparent")
        btn_row.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(btn_row, text="💾 保存设置", width=110,
                       fg_color=C["success"], hover_color=C["success_hover"],
                       command=self._save_delays).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="↩ 恢复默认", width=110,
                       fg_color=C["btn_ctrl_fg"], hover_color=C["btn_ctrl_hover"],
                       command=self._reset_delays).pack(side="left", padx=5)

        # ---- 缓存管理 ----
        card_cache = self._make_card(scroll, "📁 缓存管理")

        ctk.CTkLabel(card_cache, text=f"配置目录: {self.config['config_dir']}",
                     font=ctk.CTkFont(size=11), text_color=C["text_dim"]).pack(anchor="w")

        cache_row = ctk.CTkFrame(card_cache, fg_color="transparent")
        cache_row.pack(fill="x", pady=5)
        self.cache_label = ctk.CTkLabel(cache_row, text="截图缓存: 计算中...",
                                         font=ctk.CTkFont(size=12))
        self.cache_label.pack(side="left")
        ctk.CTkButton(cache_row, text="刷新", width=60, height=28,
                       command=self._refresh_cache).pack(side="left", padx=10)
        ctk.CTkButton(cache_row, text="🗑 清除缓存", width=90, height=28,
                       fg_color=C["danger"], hover_color=C["danger_hover"],
                       command=self._clear_cache).pack(side="left", padx=5)

        log_row = ctk.CTkFrame(card_cache, fg_color="transparent")
        log_row.pack(fill="x", pady=3)
        self.log_size_label = ctk.CTkLabel(log_row, text="日志: 计算中...",
                                            font=ctk.CTkFont(size=12))
        self.log_size_label.pack(side="left")
        ctk.CTkButton(log_row, text="📂 打开日志目录", width=120, height=28,
                       command=lambda: os.startfile(os.path.abspath(self.config["log_dir"]))
                       ).pack(side="left", padx=10)

        self._refresh_cache()

        # ---- 外观主题 ----
        card_theme = self._make_card(scroll, "🎨 外观主题")

        theme_row = ctk.CTkFrame(card_theme, fg_color="transparent")
        theme_row.pack(fill="x", pady=5)
        ctk.CTkLabel(theme_row, text="主题风格:",
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self._theme_var = ctk.StringVar(
            value={"system": "跟随系统", "light": "浅色模式", "dark": "深色模式"}[self._current_theme]
        )
        self._theme_seg = ctk.CTkSegmentedButton(
            theme_row, values=["跟随系统", "浅色模式", "深色模式"],
            variable=self._theme_var,
            command=self._on_theme_segment_change,
        )
        self._theme_seg.pack(side="right")

        # ---- 检查更新 ----
        card_update = self._make_card(scroll, "🔄 检查更新")

        update_row = ctk.CTkFrame(card_update, fg_color="transparent")
        update_row.pack(fill="x", pady=5)
        ctk.CTkLabel(update_row, text=f"当前版本: {self.config['version']}",
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self.update_btn = ctk.CTkButton(
            update_row, text="检查更新", width=100, height=30,
            fg_color=C["accent"], hover_color="#d63851",
            command=self._check_update,
        )
        self.update_btn.pack(side="right")

        self.update_result_label = ctk.CTkLabel(
            card_update, text="", font=ctk.CTkFont(size=12),
            text_color=C["text_dim"], wraplength=400, anchor="w", justify="left",
        )
        self.update_result_label.pack(fill="x", pady=(2, 8))

        return page

    # ================================================================
    # 通用卡片组件
    # ================================================================

    def _make_card(self, parent, title: str, expand: bool = False) -> ctk.CTkFrame:
        """创建一个带标题的卡片容器"""
        outer = ctk.CTkFrame(parent, fg_color=C["card_bg"], corner_radius=10)
        outer.pack(fill="x", pady=(0, 10), ipady=8, ipadx=10)
        if expand:
            outer.pack_configure(expand=True)

        ctk.CTkLabel(outer, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["accent"], anchor="w").pack(fill="x", padx=10, pady=(8, 2))

        inner = ctk.CTkFrame(outer, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        # 追踪卡片外框用于主题刷新
        if not hasattr(self, '_cards'):
            self._cards = []
        self._cards.append(outer)
        return inner

    # ================================================================
    # 日志输出
    # ================================================================

    def append_expedition_log(self, msg: str):
        """追加远征日志（线程安全）"""
        def _update():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, _update)

    def append_arena_log(self, msg: str):
        """追加竞技场日志（线程安全）"""
        def _update():
            self.arena_log_text.configure(state="normal")
            self.arena_log_text.insert("end", msg + "\n")
            self.arena_log_text.see("end")
            self.arena_log_text.configure(state="disabled")
        self.root.after(0, _update)

    # ================================================================
    # 状态更新（供 main.py 调用）
    # ================================================================

    def set_expedition_status(self, text: str, color: str = C["text_dim"]):
        def _u(): self.expedition_status.configure(text=text, text_color=color)
        self.root.after(0, _u)

    def set_arena_status(self, text: str, color: str = C["text_dim"]):
        def _u(): self.arena_status.configure(text=text, text_color=color)
        self.root.after(0, _u)

    def set_game_status(self, running: bool, detail: str = ""):
        def _u():
            if running:
                txt = f"🟢 游戏运行中" + (f" ({detail})" if detail else "")
                self.game_status_label.configure(text=txt, text_color=C["success"])
            else:
                self.game_status_label.configure(text="🔴 游戏未运行", text_color=C["danger"])
        self.root.after(0, _u)

    def set_ocr_status(self, backend: str):
        def _u(): self.ocr_status_label.configure(text=f"OCR: {backend}")
        self.root.after(0, _u)

    def update_hotkey_display(self, key_display: str):
        def _u(): self.hotkey_btn.configure(text=f"🔘 热键: {key_display}")
        self.root.after(0, _u)

    def update_arena_hotkey_display(self, key_display: str):
        def _u(): self.arena_hotkey_btn.configure(text=f"🔘 热键: {key_display}")
        self.root.after(0, _u)

    def update_fishing_hotkey_display(self, key_display: str):
        def _u(): self.fishing_hotkey_btn.configure(text=f"🔘 热键: {key_display}")
        self.root.after(0, _u)

    def minimize(self):
        self.root.after(0, self.root.iconify)

    def restore(self):
        self.root.after(0, self.root.deiconify)

    # ================================================================
    # 内部事件处理
    # ================================================================

    def _toggle_expedition(self):
        if self.on_start_expedition and self.on_stop_expedition:
            # 通过回调判断当前状态
            if hasattr(self, '_exp_running') and self._exp_running:
                self._stop_expedition()
            else:
                self._start_expedition()

    def _start_expedition(self):
        if self.on_start_expedition:
            self.on_start_expedition()

    def _stop_expedition(self):
        if self.on_stop_expedition:
            self.on_stop_expedition()

    def _toggle_arena(self):
        if hasattr(self, '_arena_running') and self._arena_running:
            self._stop_arena()
        else:
            self._start_arena()

    def _start_arena(self):
        if self.on_start_arena:
            self.on_start_arena()

    def _stop_arena(self):
        if self.on_stop_arena:
            self.on_stop_arena()

    def _on_dest_change_internal(self, value):
        if value == "多选模式":
            self.multi_btn.pack(side="left", padx=5)
            self._update_multi_status()
        else:
            self.multi_btn.pack_forget()
            self.multi_status.configure(text="")
        if self.on_dest_change:
            self.on_dest_change(value)

    def _on_auto_restart_change_internal(self):
        if self.on_auto_restart_change:
            self.on_auto_restart_change(self.auto_restart_var.get())

    def _on_ocr_mode_change_internal(self, value):
        if self.on_ocr_mode_change:
            self.on_ocr_mode_change(value == "GPU")

    def _save_delays(self):
        if self.on_save_delays:
            self.on_save_delays(self.delay_vars)

    def _reset_delays(self):
        if self.on_reset_delays:
            self.on_reset_delays(self.delay_vars)

    def _bind_hotkey(self):
        self.hotkey_btn.configure(text="🔘 请按键...")
        if self.on_bind_hotkey:
            self.on_bind_hotkey()

    def _bind_arena_hotkey(self):
        self.arena_hotkey_btn.configure(text="🔘 请按键...")
        if self.on_bind_arena_hotkey:
            self.on_bind_arena_hotkey()

    def _bind_fishing_hotkey(self):
        self.fishing_hotkey_btn.configure(text="🔘 请按键...")
        if self.on_bind_fishing_hotkey:
            self.on_bind_fishing_hotkey()

    def _update_multi_status(self):
        dests = self.config.get("multi_destinations", [])
        active = [d for d in dests if d]
        if active:
            self.multi_status.configure(text=f"队列: {' → '.join(active)}")
        else:
            self.multi_status.configure(text="队列: [未设置]")

    def _open_multi_settings(self):
        """打开多选目的地弹窗"""
        win = ctk.CTkToplevel(self.root)
        win.title("多选目的地设置")
        win.geometry("450x420")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkLabel(win, text="设置远征目的地执行顺序\n留空或选 (无) 表示跳过",
                     font=ctk.CTkFont(size=13), justify="center").pack(pady=(15, 10))

        all_values = ["（无）"] + self.config["destinations_page1"] + self.config["destinations_page2"]
        combos = []
        dests = self.config.get("multi_destinations", [None] * 6)

        for i in range(6):
            row = ctk.CTkFrame(win, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=4)
            ctk.CTkLabel(row, text=f"第 {i+1} 个:", width=60, anchor="w").pack(side="left")
            current = dests[i] if i < len(dests) and dests[i] else "（无）"
            var = ctk.StringVar(value=current)
            ctk.CTkComboBox(row, variable=var, values=all_values,
                            width=250, state="readonly").pack(side="left", padx=10)
            combos.append(var)

        def _apply():
            for i in range(6):
                val = combos[i].get()
                self.config["multi_destinations"][i] = None if val == "（无）" else val
            self._update_multi_status()
            if self.on_save_delays:
                # 触发保存（通过回调）
                pass
            win.destroy()

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=15)
        ctk.CTkButton(btn_frame, text="确定", fg_color=C["success"],
                       hover_color=C["success_hover"], command=_apply).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="取消", fg_color=C["btn_ctrl_fg"],
                       hover_color=C["btn_ctrl_hover"], command=win.destroy).pack(side="right", padx=5)

    def _refresh_cache(self):
        """刷新缓存大小显示"""
        screenshot_dir = self.config.get("screenshot_dir", "screenshots")
        log_dir = self.config["log_dir"]

        total, count = 0, 0
        if os.path.isdir(screenshot_dir):
            for f in os.listdir(screenshot_dir):
                fp = os.path.join(screenshot_dir, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
                    count += 1
        self.cache_label.configure(text=f"截图缓存: {count} 个文件, {self._fmt_size(total)}")

        log_total, log_count = 0, 0
        if os.path.isdir(log_dir):
            for f in os.listdir(log_dir):
                fp = os.path.join(log_dir, f)
                if os.path.isfile(fp) and f.endswith(".log"):
                    log_total += os.path.getsize(fp)
                    log_count += 1
        self.log_size_label.configure(text=f"日志: {log_count} 个文件, {self._fmt_size(log_total)}")

    def _clear_cache(self):
        if self.on_clear_cache:
            self.on_clear_cache()
        self._refresh_cache()

    def _check_update(self):
        """触发检查更新"""
        self.update_btn.configure(state="disabled", text="检查中...")
        self.update_result_label.configure(text="正在连接 GitHub ...", text_color=C["text_dim"])
        if self.on_check_update:
            self.on_check_update()

    def show_update_result(self, result: dict):
        """显示检查更新结果（由 main.py 回调）"""
        self.update_btn.configure(state="normal", text="检查更新")
        if result.get("error"):
            self.update_result_label.configure(
                text=f"❌ 检查失败: {result['error']}", text_color=C["danger"])
        elif result.get("available"):
            self.update_result_label.configure(
                text=f"🎉 发现新版本 {result['latest']} ！点击下方链接下载：\n{result['url']}",
                text_color=C["success"])
            # 可点击的链接
            if hasattr(self, '_update_link'):
                self._update_link.destroy()
            self._update_link = ctk.CTkButton(
                self.update_result_label.master,
                text="打开下载页面", width=140, height=28,
                fg_color=C["success"], hover_color=C["success_hover"],
                command=lambda: os.startfile(result["url"]),
            )
            self._update_link.pack(anchor="w", pady=(2, 8))
        else:
            self.update_result_label.configure(
                text=f"✅ 已是最新版本 ({result.get('latest', '')})", text_color=C["success"])

    @staticmethod
    def _fmt_size(size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    # ================================================================
    # 主题切换
    # ================================================================

    def _apply_custom_colors(self):
        """主题切换后刷新所有手动设置过颜色的组件"""
        # 侧边栏背景
        if hasattr(self, '_sidebar'):
            self._sidebar.configure(fg_color=C["sidebar_bg"])
        # Logo 和版本号
        if hasattr(self, '_logo_label'):
            self._logo_label.configure(text_color=C["accent"])
        if hasattr(self, '_ver_label'):
            self._ver_label.configure(text_color=C["text_dim"])
        # 导航按钮
        for pid, btn in self._nav_buttons.items():
            if pid == self._current_page:
                btn.configure(fg_color=C["sidebar_active"], text_color=C["text"])
            else:
                btn.configure(fg_color="transparent", text_color=C["text_dim"])
        # 侧边栏分隔线
        if hasattr(self, '_sidebar_seps'):
            for s in self._sidebar_seps:
                s.configure(fg_color=C["sidebar_sep"])
        # 底部状态标签
        if hasattr(self, 'game_status_label'):
            self.game_status_label.configure(text_color=C["danger"])
        if hasattr(self, 'ocr_status_label'):
            self.ocr_status_label.configure(text_color=C["text_dim"])
        # 卡片背景
        if hasattr(self, '_cards'):
            for card in self._cards:
                card.configure(fg_color=C["card_bg"])
        # 日志框
        for attr in ('log_text', 'arena_log_text', 'fishing_log_text'):
            if hasattr(self, attr):
                getattr(self, attr).configure(fg_color=C["log_bg"], text_color=C["text"])
        # 状态标签
        if hasattr(self, 'expedition_status'):
            self.expedition_status.configure(text_color=C["text_dim"])
        if hasattr(self, 'arena_status'):
            self.arena_status.configure(text_color=C["text_dim"])
        if hasattr(self, 'fishing_status'):
            self.fishing_status.configure(text_color=C["text_dim"])
        # 热键按钮
        for attr in ('hotkey_btn', 'arena_hotkey_btn', 'fishing_hotkey_btn'):
            if hasattr(self, attr):
                getattr(self, attr).configure(fg_color=C["btn_ctrl_fg"], hover_color=C["btn_ctrl_hover"])

    def _on_theme_segment_change(self, label: str):
        """分段按钮切换主题"""
        _label_to_key = {v: k for k, v in _THEME_LABELS.items()}
        theme = _label_to_key.get(label, "system")
        self._current_theme = theme
        ctk.set_appearance_mode(self._current_theme)
        _update_colors(self._current_theme)
        self._apply_custom_colors()
        if self.on_theme_change:
            self.on_theme_change(self._current_theme)

    def get_current_theme(self) -> str:
        """获取当前主题模式"""
        return self._current_theme

    # ================================================================
    # 运行
    # ================================================================

    def _start_system_theme_monitor(self):
        """启动系统主题变化检测（仅 system 模式下生效）"""
        self._last_detected_theme = _resolve_appearance_mode("system")
        self._poll_system_theme()

    def _poll_system_theme(self):
        """每 3 秒检测一次系统主题是否变化"""
        if self._current_theme == "system":
            detected = _resolve_appearance_mode("system")
            if detected != self._last_detected_theme:
                self._last_detected_theme = detected
                _update_colors("system")
                self._apply_custom_colors()
        self.root.after(3000, self._poll_system_theme)

    def run(self):
        self._start_system_theme_monitor()
        # 启动后延迟 3 秒自动检查更新（静默，不打扰用户）
        if self.on_check_update:
            self.root.after(3000, self._silent_check_update)
        self.root.mainloop()

    def _silent_check_update(self):
        """启动时静默检查更新，仅在发现新版本时提示"""
        def _parse_ver(v: str) -> tuple:
            v = v.lstrip("v").split("-")[0]
            return tuple(int(p) for p in v.split(".") if p.isdigit())

        def _do_check():
            import urllib.request, ssl, json as _json
            try:
                ctx = ssl.create_default_context()
                req = urllib.request.Request(
                    "https://api.github.com/repos/5566pol/PalFastExpeditions/releases",
                    headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "PalFastExpeditions"},
                )
                with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                # 取第一个非 draft 的 release
                release = None
                for r in data:
                    if not r.get("draft"):
                        release = r
                        break
                if release is None:
                    return
                latest = release.get("tag_name", "")
                url = release.get("html_url", "")
                if latest and _parse_ver(latest) > _parse_ver(self.config["version"]):
                    self.root.after(0, lambda: self._show_startup_update_hint(latest, url))
            except Exception:
                pass  # 静默失败
        import threading
        threading.Thread(target=_do_check, daemon=True).start()

    def _show_startup_update_hint(self, latest: str, url: str):
        """启动时发现新版本，在状态栏显示提示"""
        self.update_result_label.configure(
            text=f"🎉 发现新版本 {latest} ！\n{url}",
            text_color=C["success"])
        if hasattr(self, '_update_link'):
            self._update_link.destroy()
        self._update_link = ctk.CTkButton(
            self.update_result_label.master,
            text="打开下载页面", width=140, height=28,
            fg_color=C["success"], hover_color=C["success_hover"],
            command=lambda: os.startfile(url),
        )
        self._update_link.pack(anchor="w", pady=(2, 8))
