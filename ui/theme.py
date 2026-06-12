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

# ── 调色板（石墨近黑主色 · 中性灰阶 · 克制强调）────────────────────────
# 高级感来自克制：中性为主、近黑作主色、强调极少。刺眼饱和色一律避免。
BG        = "#ffffff"
CARD      = "#ffffff"   # 卡片 / 所有内容表面
SURFACE   = "#ffffff"
SUBTLE    = "#f5f5f6"   # 仅 hover
SELECT    = "#ececee"   # 选中态（中性浅灰，不刺眼）

TEXT      = "#1d1d1f"
TEXT2     = "#6e6e73"
TEXT3     = "#a8a8ad"

# 主操作 = 石墨近黑（Linear / Vercel 那种高级感），不再用亮蓝
ACCENT      = "#1d1d1f"
ACCENT_HOV  = "#37373a"
ACCENT_PRE  = "#000000"
ACCENT_SOFT = "#f0f0f2"   # 极淡中性填充（active tab 等）

# 唯一的彩色点缀：AI 用精致紫
INDIGO      = "#6e56cf"
INDIGO_HOV  = "#7c66d9"
INDIGO_SOFT = "#f5f3fc"

BORDER      = "#ececef"   # 分隔/容器边（更轻）
BORDER_IN   = "#d8d8dc"   # 输入框/按钮边
HOVER       = "rgba(0,0,0,0.04)"

SUCCESS = "#1f8f43"
DANGER  = "#d70015"
WARN    = "#b25000"

SEL_BG  = SELECT
SEL_FG  = TEXT

R_CARD = 14
R_BTN  = 9
R_IN   = 9
R_ITEM = 7


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
    QListWidget::item {{ border-radius: {R_ITEM}px; padding: 8px 9px; }}
    QListWidget::item:hover {{ background: {SUBTLE}; }}
    QListWidget::item:selected {{ background: {SELECT}; color: {TEXT}; }}

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


def menu_qss() -> str:
    """QMenu 专用样式。直接设到具体 QMenu 上，可压过父控件 bare 样式的级联，
    根治「右键/hover 菜单背景发黑」——QMenu(parent) 会继承 parent 的样式表，
    若 parent 用了无选择器的 `background:transparent` 之类，会漏进菜单导致变黑。"""
    return f"""
    QMenu {{
        background: {CARD}; color: {TEXT};
        border: 1px solid {BORDER}; border-radius: 10px; padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 16px; border-radius: 6px; margin: 1px 4px;
        background: transparent; color: {TEXT};
    }}
    QMenu::item:selected {{ background: {SUBTLE}; color: {TEXT}; }}
    QMenu::item:disabled {{ color: {TEXT3}; background: transparent; }}
    QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 10px; }}
    QMenu::icon {{ padding-left: 8px; }}
    """


def style_menu(menu):
    """给 QMenu 套上统一浅色样式并返回它。所有 QMenu(parent) 都该过一遍这个。"""
    menu.setStyleSheet(menu_qss())
    return menu


def tooltip_qss() -> str:
    """QToolTip / 内部 QTipLabel 的浅色样式（直接设到实例上，压过级联）。"""
    return (f"background: {CARD}; color: {TEXT}; border: 1px solid {BORDER};"
            f" border-radius: 6px; padding: 5px 8px; font-size: 12px;")


# ── 全局兜底：所有弹出层（菜单 / 提示）强制浅色 ──────────────────────────
# 根因：无边框 + 半透明主窗口下，QMenu / QToolTip(QTipLabel) 会继承父控件的
# bare 样式（background:transparent），漏进来后在半透明窗上合成成黑色——连
# 文本框/浏览器的「系统右键菜单」也黑。逐个设样式管不全（系统菜单是 Qt 内部建的）。
# 这里用一个 App 级事件过滤器：任何 QMenu / QTipLabel 一出现就给它套上不透明浅色样式。
def _install_popup_fix(app):
    from PyQt6.QtCore import QObject, QEvent, QTimer
    from PyQt6.QtWidgets import QMenu

    def _fix_tip(tip):
        # QToolTip 每次 showText 会重设 QTipLabel 的样式/调色板，所以要在它设完之后
        # （事件循环下一拍）再覆盖，并关掉半透明，确保不透明浅底、不发黑。
        try:
            from PyQt6.QtCore import Qt as _Qt
            tip.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, False)
            tip.setStyleSheet(tooltip_qss())
        except Exception:
            pass

    class _PopupStyler(QObject):
        def eventFilter(self, obj, event):
            t = event.type()
            if t == QEvent.Type.Polish or t == QEvent.Type.Show:
                cls = obj.metaObject().className()
                if cls == "QMenu" or isinstance(obj, QMenu):
                    if not obj.property("_oh_styled"):
                        obj.setProperty("_oh_styled", True)
                        obj.setStyleSheet(menu_qss())
                elif cls == "QTipLabel":
                    _fix_tip(obj)                      # 立即设一次
                    QTimer.singleShot(0, lambda o=obj: _fix_tip(o))   # 再覆盖一次
            return False

    styler = _PopupStyler(app)
    app.installEventFilter(styler)
    app._oh_popup_styler = styler   # 持引用，防止被回收
    return styler


def _light_palette():
    from PyQt6.QtGui import QPalette, QColor
    pal = QPalette()
    R = QPalette.ColorRole
    pal.setColor(R.Window, QColor(CARD))
    pal.setColor(R.WindowText, QColor(TEXT))
    pal.setColor(R.Base, QColor(SURFACE))
    pal.setColor(R.AlternateBase, QColor(SUBTLE))
    pal.setColor(R.Text, QColor(TEXT))
    pal.setColor(R.Button, QColor(CARD))
    pal.setColor(R.ButtonText, QColor(TEXT))
    pal.setColor(R.BrightText, QColor("#ffffff"))
    pal.setColor(R.ToolTipBase, QColor(CARD))
    pal.setColor(R.ToolTipText, QColor(TEXT))
    pal.setColor(R.Highlight, QColor(ACCENT))
    pal.setColor(R.HighlightedText, QColor("#ffffff"))
    try:
        pal.setColor(R.PlaceholderText, QColor(TEXT3))
    except Exception:
        pass
    # 禁用态文字
    for grp in (QPalette.ColorGroup.Disabled,):
        pal.setColor(grp, R.Text, QColor(TEXT3))
        pal.setColor(grp, R.WindowText, QColor(TEXT3))
        pal.setColor(grp, R.ButtonText, QColor(TEXT3))
    return pal


def apply(app):
    """统一入口：强制浅色配色 + 全局样式表 + 弹出层兜底。main.py 调用一次即可。

    关键：Qt6 默认跟随系统深/浅色。系统处于【深色模式】时，菜单/Tooltip 等原生件
    会用深色调色板 → 背景发黑（样式表盖不全）。这里强制浅色 ColorScheme + 浅色调色板，
    再叠加 app_qss() 与弹出层事件过滤器，三重保证不发黑。"""
    from PyQt6.QtCore import Qt
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)   # Qt 6.8+：强制浅色
    except Exception:
        pass
    try:
        app.setPalette(_light_palette())
    except Exception:
        pass
    app.setStyleSheet(app_qss())
    _install_popup_fix(app)
