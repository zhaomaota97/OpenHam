import asyncio
import threading
import keyboard as kb
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from core.plugin_manager import openham_plugin
from ui.screen_capture import ScreenCaptureOverlay
from utils.ocr_tools import extract_text_from_image
from core.signals import OCRSignal

_api = None
_ocr_overlay = None
_ocr_signal = None

def setup_ocr(api):
    global _api, _ocr_overlay, _ocr_signal
    _api = api
    _ocr_overlay = ScreenCaptureOverlay()
    _ocr_signal = OCRSignal()
    
    _ocr_overlay.capture_finished.connect(_on_capture_finished)
    _ocr_signal.triggered.connect(_ocr_overlay.start_capture)
    _ocr_signal.finished.connect(_on_ocr_finished)
    
    # 获取热键并注册
    ocr_hotkey_str = api.call("get_config", "ocr_hotkey", "ctrl+f12")
    clean_ocr_hotkey = ocr_hotkey_str.replace("<", "").replace(">", "")
    
    def _on_ocr_hotkey():
        _ocr_signal.triggered.emit()

    kb.add_hotkey(clean_ocr_hotkey, _on_ocr_hotkey, suppress=True)
    
def _on_ocr_finished(text: str):
    window = _api.call("get_main_window")
    window.result_label.setText("")
    if text and text.strip():
        # 自动复制到剪贴板
        app = QApplication.instance()
        if app:
            app.clipboard().setText(text)
        window.show_result("✅ 识别结果已复制到剪贴板")
        window.show_window()
    else:
        window.show_result("❌ 本地 OCR 未识别到文本")
        window.show_window()

def _on_capture_finished(pixmap: QPixmap):
    window = _api.call("get_main_window")
    window.show_window()
    window.input.clear()
    window.result_label.setStyleSheet("color: #8a7040; font-size: 12px;")
    window.result_label.setText("🔍 正在识别截屏文字…")
    
    def _bg_ocr():
        try:
            text = asyncio.run(extract_text_from_image(pixmap.toImage()))
        except Exception:
            text = ""
        _ocr_signal.finished.emit(text)
        
    threading.Thread(target=_bg_ocr, daemon=True).start()

@openham_plugin(trigger=["ocr", "提取文字", "截图翻译"], desc="框选区域识别文字", setup=setup_ocr)
def plugin_ocr(text: str):
    _ocr_signal.triggered.emit()
    return {"type": "result", "content": "✅ 请框选需要识别的区域（按 ESC 取消）"}
