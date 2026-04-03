#!/usr/bin/env python3
"""
ASCII心形图案打印脚本
功能：打印ASCII艺术风格的心形图案，并在图案下方输出数字123
"""

import sys

def print_ascii_heart():
    """打印ASCII心形图案"""
    try:
        # ASCII心形图案数据
        heart_lines = [
            "  ****     ****  ",
            " ******   ****** ",
            "******** ********",
            " *************** ",
            "  *************  ",
            "   ***********   ",
            "    *********    ",
            "     *******     ",
            "      *****      ",
            "       ***       ",
            "        *        "
        ]
        
        print("[INFO] 开始打印ASCII心形图案...")
        
        # 打印心形图案
        for line in heart_lines:
            print(line)
            
        print("[INFO] ASCII心形图案打印完成！")
        
    except Exception as e:
        print(f"[ERROR] 打印心形图案时发生错误: {e}", file=sys.stderr)
        sys.exit(1)

def print_number_123():
    """打印数字123"""
    try:
        print("[INFO] 开始打印数字123...")
        print("123")
        print("[INFO] 数字123打印完成！")
    except Exception as e:
        print(f"[ERROR] 打印数字时发生错误: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    """主函数"""
    print("=" * 50)
    print("ASCII心形图案与数字打印程序")
    print("=" * 50)
    
    try:
        # 打印心形图案
        print_ascii_heart()
        
        # 添加空行分隔
        print()
        
        # 打印数字123
        print_number_123()
        
        print("=" * 50)
        print("[SUCCESS] 程序执行完成！")
        print("=" * 50)
        
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断程序执行")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] 程序执行过程中发生未预期错误: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()