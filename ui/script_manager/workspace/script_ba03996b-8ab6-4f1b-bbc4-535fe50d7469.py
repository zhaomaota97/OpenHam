```python
#!/usr/bin/env python3
"""
ASCII Art Generator - 将图像或文本转换为ASCII艺术字符画
支持功能：
1. 图像转ASCII：将图像文件转换为灰度图并映射到ASCII字符
2. 文本转ASCII：将文本转换为艺术字体效果
"""

import sys
import os
import argparse
from typing import Optional, Tuple, List
import subprocess
import platform

# 检查并安装必要依赖
def check_and_install_dependencies():
    """检查并安装必要的Python包"""
    required_packages = []
    
    # 检查Pillow（用于图像处理）
    try:
        from PIL import Image
        print("[INFO] Pillow 库已安装")
    except ImportError:
        print("[WARN] Pillow 库未安装，将尝试安装...")
        required_packages.append("pillow")
    
    # 检查pyfiglet（用于文本艺术字）
    try:
        import pyfiglet
        print("[INFO] pyfiglet 库已安装")
    except ImportError:
        print("[WARN] pyfiglet 库未安装，将尝试安装...")
        required_packages.append("pyfiglet")
    
    # 如果有需要安装的包
    if required_packages:
        print(f"[INFO] 正在安装依赖包: {', '.join(required_packages)}")
        try:
            # 使用pip安装
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + required_packages)
            print("[SUCCESS] 依赖包安装完成")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] 安装依赖包失败: {e}")
            print("[INFO] 请手动运行: pip install pillow pyfiglet")
            return False
    
    return True

# 现在导入库（确保在检查依赖后）
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[ERROR] Pillow 库未正确安装")
    sys.exit(1)

try:
    import pyfiglet
except ImportError:
    print("[ERROR] pyfiglet 库未正确安装")
    sys.exit(1)

class ASCIIArtGenerator:
    """ASCII艺术生成器主类"""
    
    # ASCII字符集，从暗到亮排列
    ASCII_CHARS = ["@", "#", "S", "%", "?", "*", "+", ";", ":", ",", ".", " "]
    
    def __init__(self, width: int = 100, charset: Optional[List[str]] = None):
        """
        初始化ASCII艺术生成器
        
        Args:
            width: 输出ASCII艺术的宽度（字符数）
            charset: 自定义ASCII字符集，从暗到亮排列
        """
        self.width = width
        self.charset = charset or self.ASCII_CHARS
        self.charset_length = len(self.charset)
        
        print(f"[INFO] 初始化ASCII生成器，宽度: {width}字符，字符集长度: {self.charset_length}")
    
    def resize_image(self, image: Image.Image) -> Image.Image:
        """调整图像大小，保持宽高比"""
        original_width, original_height = image.size
        aspect_ratio