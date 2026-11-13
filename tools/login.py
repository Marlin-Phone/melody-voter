#!/usr/bin/env python3
"""登录工具：生成二维码 → 扫码 → 自动写入 config/setting.json 的 Cookie

实现：网易云 Web 端扫码登录（weapi），替代已被行为验证码拦截的密码登录方式
用法：
  python tools/login.py --account main # 更新指定 name 账号的 Cookie（默认 main）
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qrcode
import requests

from src.signer import weapi_encrypt

API = {
    "unikey": "https://music.163.com/weapi/login/qrcode/unikey",
    "login": "https://music.163.com/weapi/login/qrcode/client/login",
}
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "setting.json"
)


def fetch_unikey(session) -> str:
    params = weapi_encrypt({"type": 1})
    resp = session.post(API["unikey"], data=params, timeout=20).json()
    if resp.get("code") != 200 or not resp.get("unikey"):
        raise RuntimeError(f"获取 unikey 失败: {resp}")
    return resp["unikey"]


def print_qr(unikey: str):
    url = f"https://music.163.com/login?codekey={unikey}"
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print(f"请用网易云音乐 App 扫一扫以上二维码（手机端扫 📱）")
    print(f"或手机浏览器访问: {url}")


def wait_scan(session, unikey: str, timeout=120) -> str:
    """
    轮询登录状态（网易云已将 qrcheck 并入 client/login 接口）：
    801=等待扫码 802=已扫待确认 800=过期 200=成功（返回 cookie 字符串）
    """
    start = time.time()
    while time.time() - start < timeout:
        params = weapi_encrypt({"key": unikey, "type": 1})
        resp = session.post(API["login"], data=params, timeout=20).json()
        code = resp.get("code")
        if code == 200:
            cookies = resp.get("data", {}).get("cookie", "")
            if cookies:
                return cookies
            raise RuntimeError("登录成功但响应中未包含 cookie")
        if code == 802:
            print("✅ 已扫码，请在手机上确认登录...")
        elif code == 800:
            raise RuntimeError("二维码已过期，请重试")
        elif code != 801:
            print(f"⏳ 扫码状态: {code} {resp.get('message', '')}，继续等待...")
        time.sleep(1.5)
    raise TimeoutError("等待扫码超时")


def parse_cookies(cookie_str: str) -> dict:
    out = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def update_config(account_name: str, cookies: dict):
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}，请先复制 setting.example.json")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 旧单账号格式迁移：顶层 Cookie 字段并入 accounts 数组（防旧账号孤儿化）
    if "accounts" not in config:
        if "Cookie_MUSIC_U" in config:
            global_keys = {"notify_email", "email_password", "smtp_server", "smtp_port", "debug"}
            legacy = {k: v for k, v in config.items() if k not in global_keys}
            legacy.setdefault("name", "main")
            config["accounts"] = [legacy]
        else:
            config["accounts"] = []
    accounts = config["accounts"]

    target = None
    for acc in accounts:
        if acc.get("name") == account_name:
            target = acc
            break
    if target is None:
        target = {"name": account_name}
        accounts.append(target)

    target["Cookie_MUSIC_U"] = cookies.get("MUSIC_U", target.get("Cookie_MUSIC_U", ""))
    csrf = cookies.get("__csrf") or cookies.get("_csrf") or ""
    target["Cookie___csrf"] = csrf or target.get("Cookie___csrf", "")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"✅ 已写入 config/setting.json（账号: {account_name}）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="main", help="要更新 Cookie 的账号 name")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://music.163.com/",
    })

    unikey = fetch_unikey(session)
    print_qr(unikey)
    cookie_str = wait_scan(session, unikey)
    cookies = parse_cookies(cookie_str)
    if not cookies.get("MUSIC_U"):
        raise RuntimeError(f"登录成功但未拿到 MUSIC_U: {list(cookies.keys())}")
    update_config(args.account, cookies)
    print("🎉 登录成功！现在可以运行 python main.py 了")


if __name__ == "__main__":
    main()
