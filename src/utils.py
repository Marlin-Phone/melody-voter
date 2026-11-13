"""utils: 配置 / 日志 / Cookie校验 / 通知（TG Bot 为主，邮件可选）"""
import json
import os
import random
import smtplib
import sys
from email.mime.text import MIMEText

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "setting.json")
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")
LEDGER_DIR = os.path.join(BASE_DIR, "data", "ledger")


class Config:
    """读取 config/setting.json；兼容旧版单账号格式"""

    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"配置文件不存在: {path}\n请复制 config/setting.example.json 为 config/setting.json 并填写Cookie"
            )
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        # 兼容单账号旧格式：老配置是顶层字段，没有 accounts 数组
        if "accounts" not in self.data:
            self.data["accounts"] = [self.data]

    @property
    def accounts(self):
        return self.data["accounts"]

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def global_get(self, key: str, default=None):
        """全局配置（账号无关）"""
        return self.data.get(key, default)


class Logger:
    """控制台 + 文件双写日志"""

    def __init__(self, name: str = "melody-voter"):
        self.name = name
        os.makedirs(LOG_DIR, exist_ok=True)
        self.file = open(
            os.path.join(LOG_DIR, f"{name}-{__import__('datetime').date.today()}.log"),
            "a",
            encoding="utf-8",
        )

    def _write(self, level: str, msg: str):
        ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line)
        self.file.write(line + "\n")
        self.file.flush()

    def info(self, msg: str):
        self._write("INFO", msg)

    def debug(self, msg: str):
        if os.environ.get("MELODY_VOTER_DEBUG") == "1":
            self._write("DEBUG", msg)

    def warn(self, msg: str):
        self._write("WARN", msg)

    def error(self, msg: str):
        self._write("ERROR", msg)

    def close(self):
        self.file.close()


class CookieValidator:
    def __init__(self, session, logger: Logger):
        self.session = session
        self.logger = logger

    def validate(self) -> tuple:
        try:
            resp = self.session.get(
                "https://music.163.com/api/nuser/account/get", timeout=15
            ).json()
            profile = resp.get("profile")
            if profile:
                self.logger.info(f"Cookie有效，用户: {profile.get('nickname')}")
                return True, profile.get("nickname")
            return False, "Cookie无效或已过期（无法获取用户信息）"
        except Exception as e:
            return False, f"验证失败: {e}"


class Notifier:
    """通知：Telegram Bot（推荐）+ 可选 SMTP 邮件

    - TG 凭据来源（按优先级）：环境变量 TG_BOT_TOKEN / TG_CHAT_ID
      （GitHub Actions 以 secrets 注入），或 config/setting.json 全局字段
      tg_bot_token / tg_chat_id；均未配置时静默降级为 no-op
    - 邮件通道仅在配置了 notify_email 时启用
    - 任一发失败只记日志、不抛异常，不阻断评分主流程
    """

    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self.tg_token = (
            os.environ.get("TG_BOT_TOKEN", "").strip()
            or (config.global_get("tg_bot_token") or "").strip()
        )
        self.tg_chat_id = (
            os.environ.get("TG_CHAT_ID", "").strip()
            or (config.global_get("tg_chat_id") or "").strip()
        )
        self.tg_enabled = bool(self.tg_token and self.tg_chat_id)
        self.email_enabled = bool(config.global_get("notify_email"))

    def send(self, subject: str, body: str):
        """发送通知（TG + 邮件，各自独立降级）"""
        self.send_tg(subject, body)
        if self.email_enabled:
            self.send_email(subject, body)

    def send_tg(self, subject: str, body: str):
        if not self.tg_enabled:
            return
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                json={
                    "chat_id": self.tg_chat_id,
                    "text": f"{subject}\n\n{body}",
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
            if not resp.json().get("ok"):
                raise RuntimeError(f"TG API 错误: {resp.text[:200]}")
            self.logger.info(f"Telegram 通知已发送: {subject}")
        except Exception as e:
            self.logger.error(f"Telegram 通知发送失败: {e}")

    def send_email(self, subject: str, body: str):
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = self.config.global_get("notify_email")
            msg["To"] = self.config.global_get("notify_email")
            with smtplib.SMTP_SSL(
                self.config.global_get("smtp_server"),
                self.config.global_get("smtp_port"),
                timeout=15,
            ) as server:
                server.login(
                    self.config.global_get("notify_email"),
                    self.config.global_get("email_password"),
                )
                server.send_message(msg)
            self.logger.info(f"通知邮件已发送: {subject}")
        except Exception as e:
            self.logger.error(f"发送通知失败: {e}")


def random_delay(a=None, b=None):
    """随机等待，模拟人工操作防风控"""
    a = a if a is not None else 15
    b = b if b is not None else 20
    t = random.uniform(a, b)
    return t