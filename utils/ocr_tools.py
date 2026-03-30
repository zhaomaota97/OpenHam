import asyncio
from PyQt6.QtGui import QImage
import winrt.windows.media.ocr as ocr
import winrt.windows.graphics.imaging as imaging
import winrt.windows.storage.streams as streams

def qimage_to_softwarebitmap(qimg: QImage):
    """
    Converts a PyQt QImage into a Windows Runtime SoftwareBitmap.
    """
    # Convert to ARGB32 (or RGBA8888 equivalent)
    qimg = qimg.convertToFormat(QImage.Format.Format_ARGB32)
    width = qimg.width()
    height = qimg.height()
    
    ptr = qimg.bits()
    ptr.setsize(qimg.sizeInBytes())
    buf = bytes(ptr)
    
    # Write to WinRT DataWriter
    data_writer = streams.DataWriter()
    data_writer.write_bytes(buf)
    buffer = data_writer.detach_buffer()
    
    # Create SoftwareBitmap and copy pixels
    # QImage ARGB32 corresponds to BGRA8 in WinRT
    bm = imaging.SoftwareBitmap(imaging.BitmapPixelFormat.BGRA8, width, height)
    bm.copy_from_buffer(buffer)
    return bm

import re

async def extract_text_from_image(qimg: QImage) -> str:
    """
    Asynchronously extracts text from a QImage using Windows Media OCR.
    """
    engine = ocr.OcrEngine.try_create_from_user_profile_languages()
    if not engine:
        return ""
        
    try:
        bm = qimage_to_softwarebitmap(qimg)
        result = await engine.recognize_async(bm)
        
        text = result.text
        # WinRT OCR 会在每个中文字符间强加空格。使用正则去除中文字符之间的多余空格
        text = re.sub(r'([^\x00-\xff])\s+([^\x00-\xff])', r'\1\2', text)
        # 去除中文字符和英文字符之间的空格（通常也是不必要的）
        text = re.sub(r'([^\x00-\xff])\s+([\x00-\xff])', r'\1\2', text)
        text = re.sub(r'([\x00-\xff])\s+([^\x00-\xff])', r'\1\2', text)
        
        return text.strip()
    except Exception as e:
        print(f"[OCR] Error: {e}")
        return ""
