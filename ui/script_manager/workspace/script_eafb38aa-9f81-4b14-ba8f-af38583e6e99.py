#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化新闻爬取、发布、通知及游戏脚本
环境：Windows 11
"""

import sys
import os
import time
import logging
import traceback
import subprocess
import smtplib
import json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict, Any

# 第三方库导入检查
try:
    import requests
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
except ImportError as e:
    print(f"错误：缺少必要的Python库。请运行: pip install requests beautifulsoup4 selenium")
    sys.exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("news2lol.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置常量（用户需要根据实际情况修改）
CONFIG = {
    # 爬虫配置
    "bbc_url": "https://www.bbc.com/news",
    "zaobao_url": "https://www.zaobao.com/news",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    
    # 知乎配置（需要真实账户）
    "zhihu_login_url": "https://www.zhihu.com/signin",
    "zhihu_post_url": "https://zhuanlan.zhihu.com/write",
    "zhihu_username": "",  # 请填写
    "zhihu_password": "",  # 请填写
    
    # 邮件配置
    "smtp_server": "smtp.qq.com",  # 示例使用QQ邮箱
    "smtp_port": 587,
    "email_sender": "",  # 发件人邮箱
    "email_password": "",  # 发件人邮箱授权码
    "email_recipient": "ponyma@tencent.com",  # 马化腾邮箱（示例）
    
    # 游戏配置
    "lol_path": r"C:\Riot Games\League of Legends\LeagueClient.exe",
    "game_wait_time": 180,  # 游戏启动等待时间（秒）
    "match_duration": 1800,  # 每局游戏模拟时长（秒）
}

class News2LoLScript:
    def __init__(self):
        self.news_data = []
        self.driver = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": CONFIG["user_agent"]})
        
    def log_step(self, step_num: int, description: str):
        """记录步骤日志"""
        logger.info(f"步骤 {step_num}: {description}")
        print(f"\n{'='*60}")
        print(f"步骤 {step_num}: {description}")
        print(f"{'='*60}")
    
    def check_config(self):
        """检查必要配置是否填写"""
        missing = []
        for key, value in CONFIG.items():
            if isinstance(value, str) and value.strip() == "" and key in [
                "zhihu_username", "zhihu_password", "email_sender", "email_password"
            ]:
                missing.append(key)
        
        if missing:
            logger.error(f"配置缺失: {missing}")
            print("错误：以下配置项未填写，请在脚本中修改CONFIG字典：")
            for item in missing:
                print(f"  - {item}")
            return False
        return True
    
    def step1_crawl_news(self):
        """步骤1：爬取BBC和联合早报新闻"""
        self.log_step(1, "开始爬取BBC和联合早报新闻数据")
        
        try:
            # 爬取BBC新闻
            logger.info(f"访问BBC: {CONFIG['bbc_url']}")
            response = self.session.get(CONFIG['bbc_url'], timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            bbc_articles = []
            for item in soup.select('a[data-testid="internal-link"]')[:5]:  # 取前5条
                title = item.get_text(strip=True)
                link = item.get('href')
                if title and link:
                    if not link.startswith('http'):
                        link = 'https://www.bbc.com' + link
                    bbc_articles.append({
                        "source": "BBC",
                        "title": title,
                        "url": link,
                        "timestamp": datetime.now().isoformat()
                    })
            
            # 爬取联合早报新闻
            logger.info(f"访问联合早报: {CONFIG['zaobao_url']}")
            response = self.session.get(CONFIG['zaobao_url'], timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            zaobao_articles = []
            for item in soup.select('a.article-title, a.title')[:5]:  # 取前5条
                title = item.get_text(strip=True)
                link = item.get('href')
                if title and link:
                    if not link.startswith('http'):
                        link = 'https://www.zaobao.com' + link
                    zaobao_articles.append({
                        "source": "联合早报",
                        "title": title,
                        "url": link,
                        "timestamp": datetime.now().isoformat()
                    })
            
            self.news_data = bbc_articles + zaobao_articles
            
            if not self.news_data:
                raise Exception("未爬取到任何新闻数据")
            
            logger.info(f"成功爬取 {len(self.news_data)} 条新闻")
            print(f"爬取结果:")
            for i, news in enumerate(self.news_data, 1):
                print(f"  {i}. [{news['source']}] {news['title'][:50]}...")
            
            # 保存到文件
            with open("news_data.json", "w", encoding="utf-8") as f:
                json.dump(self.news_data, f, ensure_ascii=False, indent=2)
            
            return True
            
        except Exception as e:
            logger.error(f"爬取新闻失败: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def step2_post_to_zhihu(self):
        """步骤2：发布到知乎"""
        self.log_step(2, "开始发布新闻到知乎")
        
        if not self.news_data:
            logger.error("没有新闻数据可发布")
            return False
        
        try:
            # 初始化Selenium WebDriver
            options = webdriver.ChromeOptions()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # 登录知乎
            logger.info("正在登录知乎...")
            self.driver.get(CONFIG["zhihu_login_url"])
            time.sleep(3)
            
            # 这里简化登录过程，实际需要根据知乎页面结构调整
            # 注意：知乎有反爬机制，可能需要验证码或使用cookie登录
            print("注意：知乎登录需要人工干预或使用cookie方式")
            print("请手动登录后按回车继续...")
            input()
            
            # 创建文章
            logger.info("准备发布文章...")
            self.driver.get(CONFIG["zhihu_post_url"])
            time.sleep(5)
            
            # 填写标题和内容
            title = f"今日国际新闻摘要 {datetime.now().strftime('%Y-%m-%d')}"
            content = "# 今日新闻摘要\n\n"
            
            for news in self.news_data:
                content += f"## {news['source']}\n"
                content += f"**{news['title']}**\n"
                content += f"[阅读原文]({news['url']})\n\n"
            
            content += f"\n*自动采集于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
            
            # 这里简化发布过程，实际需要找到正确的页面元素
            print(f"文章内容已准备，标题: {title}")
            print("由于知乎页面结构复杂，建议手动发布")
            print("文章内容已保存到 'zhihu_article.md'")
            
            with open("zhihu_article.md", "w", encoding="utf-8") as f:
                f.write(content)
            
            logger.info("知乎发布流程完成（需要手动操作）")
            return True
            
        except Exception as e:
            logger.error(f"知乎发布失败: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
        finally:
            if self.driver:
                self.driver.quit()
    
    def step3_send_email(self):
        """步骤3：发送邮件抄送给马化腾"""
        self.log_step(3, "开始发送邮件通知")
        
        if not self.news_data:
            logger.error("没有新闻数据可发送")
            return False
        
        try:
            # 准备邮件内容
            subject = f"今日新闻摘要 {datetime.now().strftime('%Y-%m-%d')}"
            
            html_content = """
            <html>
            <body>
                <h2>今日新闻摘要</h2>
                <p>以下为自动采集的BBC和联合早报新闻：</p>
            """
            
            for news in self.news_data:
                html_content += f"""
                <div style="margin-bottom: 15px; padding: 10px; border-left: 3px solid #1890ff;">
                    <h3 style="margin: 0 0 5px 0;">{news['source']}</h3>
                    <p style="margin: 0 0 5px 0;"><strong>{news['title']}</strong></p>
                    <p style="margin: 0;"><a href="{news['url']}">阅读原文</a></p>
                </div>
                """
            
            html_content += f"""
                <hr>
                <p style="color: #666; font-size: 12px;">
                    此邮件由自动化脚本发送<br>
                    时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
            </body>
            </html>
            """
            
            # 创建邮件
            msg = MIMEMultipart()
            msg['From'] = CONFIG['email_sender']
            msg['To'] = CONFIG['email_recipient']
            msg['Subject'] = subject
            
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))
            
            # 发送邮件
            logger.info(f"连接SMTP服务器: {CONFIG['smtp_server']}")
            with smtplib.SMTP(CONFIG['smtp_server'], CONFIG['smtp_port']) as server:
                server.starttls()
                server.login(CONFIG['email_sender'], CONFIG['email_password'])
                server.send_message(msg)
            
            logger.info(f"邮件已发送至: {CONFIG['email_recipient']}")
            print(f"✓ 邮件发送成功")
            return True
            
        except Exception as e:
            logger.error(f"邮件发送失败: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def step4_open_lol(self):
        """步骤4：打开英雄联盟"""
        self.log_step(4, "启动英雄联盟客户端")
        
        try:
            # 检查游戏路径
            if not os.path.exists(CONFIG['lol_path']):
                logger.error(f"游戏路径不存在: {CONFIG['lol_path']}")
                print(f"请检查游戏安装路径，或修改CONFIG中的'lol_path'")
                return False
            
            # 启动游戏
            logger.info(f"启动游戏: {CONFIG['lol_path']}")
            subprocess.Popen([CONFIG['lol_path']])
            
            print(f"游戏已启动，等待 {CONFIG['game_wait_time']} 秒加载...")
            for i in range(CONFIG['game_wait_time'] // 10):
                print(f"  等待中... {i*10}/{CONFIG['game_wait_time']}秒")
                time.sleep(10)
            
            print("✓ 游戏启动完成")
            return True
            
        except Exception as e:
            logger.error(f"启动游戏失败: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def step5_play_ranked(self):
        """步骤5：模拟进行3局排位赛"""
        self.log_step(5, "开始模拟3局排位赛")
        
        try:
            print("注意：此步骤为模拟游戏过程")
            print("实际游戏操作需要与游戏客户端交互，这里仅模拟等待时间")
            
            for match in range(1, 4):
                logger.info(f"开始第 {match} 局排位赛")
                print(f"\n第 {match} 局排位赛开始...")
                
                # 模拟游戏进行时间
                for i in range(CONFIG['match_duration'] // 60):
                    if i % 5 == 0:
                        print(f"  游戏进行中... {i}分钟/{CONFIG['match_duration']//60}分钟")
                    time.sleep(60)
                
                # 模拟游戏结果
                import random
                result = random.choice(["胜利", "失败"])
                logger.info(f"第 {match} 局结束: {result}")
                print(f"第 {match} 局结束: {result}")
                
                if match < 3:
                    print("准备下一局比赛...")
                    time.sleep(60)  # 等待1分钟
            
            print("\n✓ 3局排位赛模拟完成")
            return True
            
        except Exception as e:
            logger.error(f"游戏模拟失败: {str(e)}")
            logger.debug(traceback.format_exc())
            return False
    
    def cleanup(self):
        """清理资源"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
    
    def run(self):
        """主执行流程"""
        print("="*60)
        print("新闻爬取、发布、通知及游戏自动化脚本")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        
        try:
            # 检查配置
            if not self.check_config():
                return False
            
            # 执行所有步骤
            steps = [
                self.step1_crawl_news,
                self.step2_post_to_zhihu,
                self.step3_send_email,
                self.step4_open_lol,
                self.step5_play_ranked
            ]
            
            for i, step_func in enumerate(steps, 1):
                if not step_func():
                    logger.error(f"步骤 {i} 执行失败，脚本终止")
                    print(f"\n✗ 步骤 {i} 执行失败，请查看日志文件 'news2lol.log'")
                    return False
            
            print("\n" + "="*60)
            print("所有任务完成！")
            print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*60)
            return True
            
        except KeyboardInterrupt:
            print("\n\n脚本被用户中断")
            return False
        except Exception as e:
            logger.error(f"脚本执行异常: {str(e)}")
            logger.debug(traceback.format_exc())
            print(f"\n✗ 脚本执行异常: {str(e)}")
            return False
        finally:
            self.cleanup()

if __name__ == "__main__":
    script = News2LoLScript()
    success = script.run()
    sys.exit(0 if success else 1)