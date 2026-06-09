"""OpenHam「精致白」主题：统一配色 + 全局样式。

设计目标：常见的 mac 浅色风格，高级、精致、交互良好。关闭按钮仍在右上角
（不学 mac 红绿灯）。所有颜色集中在此，窗口样式引用这里的常量，便于一致与维护。
"""

# ── 调色板（Apple 风浅色）──────────────────────────────────────────────
BG        = "#f5f5f7"   # 窗口底 / 次级面板
CARD      = "#ffffff"   # 卡片表面
SURFACE   = "#ffffff"   # 输入框/列表底
SUBTLE    = "#f5f5f7"   # 轻微填充（ghost hover / 占位面板）

TEXT      = "#1d1d1f"   # 主文字
TEXT2     = "#86868b"   # 次文字
TEXT3     = "#b0b0b5"   # 占位 / 三级

ACCENT      = "#0071e3"  # 主强调（蓝）
ACCENT_HOV  = "#0077ed"
ACCENT_PRE  = "#006edb"
ACCENT_SOFT = "#e8f1fd"  # 浅蓝填充

INDIGO      = "#5e5ce6"  # AI（靛）
INDIGO_HOV  = "#6e6cf0"
INDIGO_SOFT = "#ececfd"

BORDER      = "#e5e5ea"  # 分隔线
BORDER_IN   = "#d2d2d7"  # 输入框边
HOVER       = "rgba(0,0,0,0.05)"
HOVER_STR   = "rgba(0,0,0,0.08)"

SUCCESS = "#34c759"
DANGER  = "#ff3b30"
WARN    = "#ff9500"

# 选中态
SEL_BG  = ACCENT
SEL_FG  = "#ffffff"

# 圆角
R_CARD = 12
R_BTN  = 8
R_IN   = 8
R_ITEM = 6


# ── 全局样式（app.setStyleSheet）──────────────────────────────────────
# 主要负责那些没有各自 _qss 的标准控件：菜单、提示、滚动条、消息框、对话框。
def app_qss() -> str:
    return f"""
    QToolTip {{
        background: {CARD}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
    }}
    QMenu {{
        background: {CARD}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 10px; padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 16px; border-radius: 6px; margin: 1px 4px;
    }}
    QMenu::item:selected {{ background: {SUBTLE}; color: {TEXT}; }}
    QMenu::item:disabled {{ color: {TEXT3}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 10px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: #c7c7cc; border-radius: 5px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #aeaeb2; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: #c7c7cc; border-radius: 5px; min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: #aeaeb2; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QMessageBox, QInputDialog, QFileDialog {{ background: {CARD}; }}
    QMessageBox QLabel, QInputDialog QLabel {{ color: {TEXT}; font-size: 13px; }}
    QDialog {{ background: {CARD}; color: {TEXT}; }}
    QMessageBox QPushButton, QInputDialog QPushButton, QDialog QPushButton {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER_IN}; border-radius: {R_BTN}px;
        padding: 6px 16px; font-size: 13px; min-width: 64px;
    }}
    QMessageBox QPushButton:hover, QInputDialog QPushButton:hover,
    QDialog QPushButton:hover {{ background: {SUBTLE}; }}
    QMessageBox QPushButton:default, QInputDialog QPushButton:default {{
        background: {ACCENT}; color: #ffffff; border: none;
    }}
    QMessageBox QPushButton:default:hover, QInputDialog QPushButton:default:hover {{
        background: {ACCENT_HOV};
    }}
    QPlainTextEdit, QTextEdit, QLineEdit {{
        selection-background-color: {ACCENT}; selection-color: #ffffff;
    }}
    """
