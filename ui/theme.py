"""OpenHam「精致白」主题：统一配色 + 全局组件规范。

设计目标：常见的 mac 浅色风格，高级、精致、交互良好，**整体一致**。关闭按钮仍在
右上角（不学 mac 红绿灯）。

一致性原则（全局唯一真相）：
- 内容表面一律白色；灰色只用于 hover，不当作面板/按钮底色。
- 按钮只有三类：主操作=蓝实心；其余=白底+细边；AI=白底+靛字（低调）。无灰填充按钮。
- 蓝只出现在：主按钮、选中项、聚焦边框、开关开启态。不滥用。
- 用 1px 细边框（而非灰底块）做区隔。

各窗口尽量不再自带样式表，统一继承这里的 app_qss()；只有结构性差异才局部覆盖。
"""

# ── 调色板 ────────────────────────────────────────────────────────────
BG        = "#f5f5f7"   # 仅 hover / 极少数次级底
CARD      = "#ffffff"   # 卡片 / 所有内容表面
SURFACE   = "#ffffff"
SUBTLE    = "#f5f5f7"   # hover

TEXT      = "#1d1d1f"
TEXT2     = "#86868b"
TEXT3     = "#b0b0b5"

ACCENT      = "#0071e3"
ACCENT_HOV  = "#0077ed"
ACCENT_PRE  = "#006edb"
ACCENT_SOFT = "#eaf2fd"

INDIGO      = "#5e5ce6"
INDIGO_HOV  = "#6e6cf0"
INDIGO_SOFT = "#f3f2ff"

BORDER      = "#e8e8ed"   # 分隔/容器边
BORDER_IN   = "#d2d2d7"   # 输入框/按钮边
HOVER       = "rgba(0,0,0,0.05)"

SUCCESS = "#248a3d"
DANGER  = "#d70015"
WARN    = "#b25000"

SEL_BG  = ACCENT
SEL_FG  = "#ffffff"

R_CARD = 12
R_BTN  = 8
R_IN   = 8
R_ITEM = 6


def app_qss() -> str:
    return f"""
    /* ── 文本 ─────────────────────────────────────────── */
    QLabel {{ color: {TEXT}; font-size: 13px; background: transparent; }}
    QLabel#hint, QLabel#secondary {{ color: {TEXT2}; font-size: 12px; }}
    QLabel#status {{ color: {TEXT}; font-size: 13px; font-weight: 600; }}

    /* ── 按钮：默认=白底细边 ───────────────────────────── */
    QPushButton {{
        background: {CARD}; color: {TEXT};
        border: 1px solid {BORDER_IN}; border-radius: {R_BTN}px;
        padding: 7px 14px; font-size: 13px;
    }}
    QPushButton:hover {{ background: {SUBTLE}; }}
    QPushButton:pressed {{ background: #ececef; }}
    QPushButton:disabled {{ color: {TEXT3}; background: {SUBTLE}; border-color: {BORDER}; }}
    /* 主操作=蓝实心 */
    QPushButton#primary {{ background: {ACCENT}; color: #ffffff; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {ACCENT_HOV}; }}
    QPushButton#primary:pressed {{ background: {ACCENT_PRE}; }}
    QPushButton#primary:disabled {{ background: #a9cdf5; color: #ffffff; }}
    /* AI=白底靛字（低调） */
    QPushButton#ai {{ background: {CARD}; color: {INDIGO}; border: 1px solid {BORDER_IN}; font-weight: 500; }}
    QPushButton#ai:hover {{ background: {INDIGO_SOFT}; border-color: #d8d6fb; }}
    /* 危险=白底红字 */
    QPushButton#danger {{ color: {DANGER}; }}
    QPushButton#danger:hover {{ background: #fff0ef; border-color: #ffd4d1; }}

    /* ── 输入 ─────────────────────────────────────────── */
    QLineEdit, QPlainTextEdit {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER_IN}; border-radius: {R_IN}px; padding: 7px 10px;
        selection-background-color: {ACCENT}; selection-color: #ffffff;
    }}
    QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit:disabled {{ color: {TEXT3}; background: {SUBTLE}; }}
    QLineEdit::placeholder {{ color: {TEXT3}; }}

    QTextEdit {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 10px;
        selection-background-color: {ACCENT}; selection-color: #ffffff;
    }}

    /* ── 列表 ─────────────────────────────────────────── */
    QListWidget {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 10px; outline: none; padding: 4px;
    }}
    QListWidget::item {{ border-radius: {R_ITEM}px; padding: 7px 8px; }}
    QListWidget::item:hover {{ background: {SUBTLE}; }}
    QListWidget::item:selected {{ background: {ACCENT}; color: #ffffff; }}

    /* ── 下拉框 ───────────────────────────────────────── */
    QComboBox {{
        background: {SURFACE}; color: {TEXT};
        border: 1px solid {BORDER_IN}; border-radius: {R_IN}px; padding: 6px 10px;
    }}
    QComboBox:hover {{ border-color: {ACCENT}; }}
    QComboBox QAbstractItemView {{
        background: {CARD}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 8px; outline: none;
        selection-background-color: {ACCENT}; selection-color: #ffffff;
    }}

    /* ── 勾选 ─────────────────────────────────────────── */
    QCheckBox, QRadioButton {{ color: {TEXT}; spacing: 7px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}

    /* ── 标签页（脚本管理运行日志）────────────────────── */
    QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; top: -1px; }}
    QTabBar::tab {{
        background: transparent; color: {TEXT2};
        border: none; padding: 7px 14px; margin-right: 2px;
        border-top-left-radius: 8px; border-top-right-radius: 8px;
    }}
    QTabBar::tab:selected {{ color: {ACCENT}; background: {ACCENT_SOFT}; }}
    QTabBar::tab:hover:!selected {{ background: {SUBTLE}; }}

    /* ── 菜单 / 提示 ───────────────────────────────────── */
    QToolTip {{
        background: {CARD}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
    }}
    QMenu {{
        background: {CARD}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 10px; padding: 6px;
    }}
    QMenu::item {{ padding: 7px 16px; border-radius: 6px; margin: 1px 4px; }}
    QMenu::item:selected {{ background: {SUBTLE}; color: {TEXT}; }}
    QMenu::item:disabled {{ color: {TEXT3}; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 10px; }}

    /* ── 滚动条 ───────────────────────────────────────── */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #c7c7cc; border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: #aeaeb2; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: #c7c7cc; border-radius: 5px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: #aeaeb2; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ── 对话框 ───────────────────────────────────────── */
    QMessageBox, QInputDialog, QFileDialog, QDialog {{ background: {CARD}; color: {TEXT}; }}
    QMessageBox QLabel, QInputDialog QLabel {{ color: {TEXT}; font-size: 13px; }}
    QMessageBox QPushButton, QInputDialog QPushButton, QDialog QPushButton {{ min-width: 64px; }}
    QMessageBox QPushButton:default, QInputDialog QPushButton:default {{
        background: {ACCENT}; color: #ffffff; border: none;
    }}
    QMessageBox QPushButton:default:hover, QInputDialog QPushButton:default:hover {{ background: {ACCENT_HOV}; }}
    """
