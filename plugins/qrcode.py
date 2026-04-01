from core.plugin_manager import openham_plugin
from utils.system_tools import generate_qr_bytes
from PyQt6.QtWidgets import QApplication

@openham_plugin(trigger=["转二维码", "qr"], desc="剪贴板文字 → 二维码")
def plugin_qrcode(text: str):
    clip = QApplication.clipboard().text().strip()
    if not clip:
        return {"type": "error", "content": "❌ 剪贴板为空"}
    png = generate_qr_bytes(clip)
    if png is None:
        return {"type": "error", "content": "❌ 请先安装 qrcode 库"}
    return {"type": "qr", "content": png}
