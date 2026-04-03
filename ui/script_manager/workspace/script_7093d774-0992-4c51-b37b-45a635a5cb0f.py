import datetime
import sys

def main():
    """
    主函数：获取并打印当前时间
    """
    try:
        # 获取当前时间
        current_time = datetime.datetime.now()
        
        # 格式化为易读的字符串
        formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 打印结果
        print(f"当前系统时间: {formatted_time}")
        
        # 成功退出
        sys.exit(0)
        
    except Exception as e:
        # 捕获并处理所有异常
        print(f"错误: 无法获取当前时间 - {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()