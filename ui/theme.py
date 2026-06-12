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
    """QMenu 浅色样式：白底、圆角、细描边、item 选中浅灰。配合 WA_TranslucentBackground
    使圆角平滑生效；颜色由全局浅色 ColorScheme/Palette 保证不发黑。"""
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
    """给 QMenu 套统一浅色 + 透明圆角(平滑、无重阴影)。所有 QMenu(parent) 都该过一遍。"""
    try:
        from PyQt6.QtCore import Qt as _Qt
        menu.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, True)
    except Exception:
        pass
    menu.setStyleSheet(menu_qss())
    return menu


# ── 全局兜底：菜单/Tooltip 走 Qt 标准做法 = 透明窗 + QSS 圆角(平滑) ─────────
# 关键教训：圆角平滑只能靠 WA_TranslucentBackground(透明窗+QSS border-radius)，遮罩会锯齿；
# 而本机之前透明窗发黑【不是透明本身的错，是误调了 disable_native_window_effects(DWMNCRP_DISABLED)
# 破坏了分层窗合成】——只要不去碰原生 NC 渲染，透明圆角窗就正常(主窗口同款，平滑且无重阴影)。
# tooltip 仍自绘(系统 QToolTip 复用 QTipLabel 深色反复回黑，防不胜防)，但用透明圆角 QLabel。
def _install_popup_fix(app):
    from PyQt6.QtCore import QObject, QEvent, QTimer, Qt, QPoint
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QMenu, QLabel, QWidget

    class _PopupFix(QObject):
        def __init__(self, parent):
            super().__init__(parent)
            self._tip = None
            self._hide_timer = QTimer(self)
            self._hide_timer.setSingleShot(True)
            self._hide_timer.timeout.connect(self._hide_tip)

        def _ensure_tip(self):
            if self._tip is None:
                lbl = QLabel(None)
                # 透明圆角窗(平滑、不发黑)；绝不对它调 disable_native_window_effects。
                lbl.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                                   | Qt.WindowType.NoDropShadowWindowHint)
                lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                lbl.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
                lbl.setStyleSheet(
                    f"QLabel {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER_IN};"
                    f" border-radius: 8px; padding: 6px 10px; font-size: 12px; }}")
                self._tip = lbl
            return self._tip

        def _show_tip(self, text, gpos):
            t = self._ensure_tip()
            t.setText(text)
            t.adjustSize()
            t.move(gpos + QPoint(12, 18))
            t.show()
            t.raise_()
            self._hide_timer.start(6000)

        def _hide_tip(self):
            if self._tip is not None and self._tip.isVisible():
                self._tip.hide()

        def eventFilter(self, obj, event):
            et = event.type()
            if et == QEvent.Type.ToolTip:
                text = obj.toolTip() if isinstance(obj, QWidget) else ""
                if text:
                    gpos = None
                    try:
                        gpos = event.globalPos()
                    except Exception:
                        gpos = QCursor.pos()
                    self._show_tip(text, gpos or QCursor.pos())
                    return True            # 吃掉系统 tooltip，用我们自绘的
                self._hide_tip()
                return False
            if et in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel,
                      QEvent.Type.WindowDeactivate, QEvent.Type.FocusOut,
                      QEvent.Type.KeyPress):
                self._hide_tip()
            elif et == QEvent.Type.Polish or et == QEvent.Type.Show:
                if isinstance(obj, QMenu) or obj.metaObject().className() == "QMenu":
                    if not obj.property("_oh_styled"):
                        obj.setProperty("_oh_styled", True)
                        try:               # 透明窗 → QSS 圆角平滑生效(不发黑、无遮罩锯齿)
                            obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                        except Exception:
                            pass
                        obj.setStyleSheet(menu_qss())
            return False

    fix = _PopupFix(app)
    app.installEventFilter(fix)
    app._oh_popup_styler = fix   # 持引用，防止被回收
    return fix


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
    # QToolTip 复用同一个内部 label，每次 showText 会重设它的【静态调色板】(深色模式下是黑的)，
    # 所以快速在控件间移动时复用的 tooltip 又变黑。直接把 QToolTip 的静态调色板设成浅色，根治。
    try:
        from PyQt6.QtWidgets import QToolTip
        QToolTip.setPalette(_light_palette())
    except Exception:
        pass
    app.setStyleSheet(app_qss())
    _install_popup_fix(app)
