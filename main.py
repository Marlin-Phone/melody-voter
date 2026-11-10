#!/usr/bin/env python3
"""melody-voter: 网易云音乐合伙人自动化助手

运行：python main.py            # 执行每日任务
      python main.py --report  # 查看当前结算期达标进度

配置：复制 config/setting.example.json 为 config/setting.json 并填写 Cookie
"""
import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from src.ledger import Ledger
from src.signer import ScoreEngine
from src.tasks import DailyTask, ExtraTask
from src.utils import Config, CookieValidator, Logger, Notifier


def run_account(account: dict, debug: bool = False):
    name = account.get("name", "default")
    logger = Logger(name)

    session = requests.Session()
    session.cookies.set("MUSIC_U", account.get("Cookie_MUSIC_U", ""))
    session.cookies.set("__csrf", account.get("Cookie___csrf", ""))

    config = {**account, "_debug": debug, "_comment_pool": account.get("comment_pool", [])}

    cfg = Config()
    notifier = Notifier(cfg, logger)

    # 1. Cookie 校验
    ok, msg = CookieValidator(session, logger).validate()
    if not ok:
        logger.error(f"[{name}] {msg}")
        notifier.send("melody-voter Cookie失效", f"{name}: {msg}")
        return {"name": name, "error": msg}

    # 2. 评分引擎（权重策略 + 评论）
    engine = ScoreEngine(
        weights=account.get("score_weights"),
        jitter=account.get("jitter", True),
    )
    pick_score = engine.pick_score
    tags_cb = engine.tags_for
    comment_cb = (
        (lambda: engine.comment_for(config["_comment_pool"]))
        if account.get("enable_comment", True) and config["_comment_pool"]
        else (lambda: "")
    )

    # 3. 基础任务
    daily = DailyTask(session, logger, config)
    complete, task_data = daily.get_tasks()
    if not complete and task_data.get("works"):
        daily_result = daily.run(pick_score, tags_cb, comment_cb)
    else:
        daily_result = {"type": "daily", "done": 0, "failed": 0, "id": str(task_data.get("id", ""))}

    # 4. 额外任务（使用每日任务 task_id，新协议需要）
    extra = ExtraTask(session, logger, config)
    try:
        extra_result = extra.run(
            pick_score, tags_cb, comment_cb, task_id=daily_result.get("id", "")
        )
    except Exception as e:
        logger.error(f"额外任务失败: {e}")
        extra_result = {"type": "extra", "done": 0, "failed": 0}

    total_done = daily_result.get("done", 0) + extra_result.get("done", 0)
    total_failed = daily_result.get("failed", 0) + extra_result.get("failed", 0)

    # 5. 记账 + 报告（结算期锚点与达标线均为 Ledger 内置常量，自动计算）
    ledger = Ledger(name=name)
    if total_done or total_failed:
        ledger.record(total_done, total_failed, note="auto")
    logger.info(f"[{name}] 本次完成 {total_done} 首，失败 {total_failed} 首")
    logger.info(ledger.print_report())

    notifier.send(
        f"melody-voter [{name}] 任务完成",
        f"本次完成 {total_done} 首，失败 {total_failed} 首",
    )
    return {"name": name, "done": total_done, "failed": total_failed}


def main():
    parser = argparse.ArgumentParser(description="melody-voter 网易云音乐合伙人自动化助手")
    parser.add_argument("--report", action="store_true", help="只打印当前结算期达标报告")
    parser.add_argument("--account", default="", help="只运行指定账号（name）")
    args = parser.parse_args()

    config = Config()
    debug = bool(config.global_get("debug", False))

    if args.report:
        for acc in config.accounts:
            ledger = Ledger(name=acc.get("name", "default"))
            print(ledger.print_report())
            print()
        return

    targets = config.accounts
    if args.account:
        targets = [a for a in config.accounts if a.get("name") == args.account]
        if not targets:
            print(f"未找到账号: {args.account}")
            sys.exit(1)

    for acc in targets:
        try:
            run_account(acc, debug)
        except Exception as e:
            print(f"账号 {acc.get('name', '?')} 运行异常: {e}")
        # 账号间随机间隔，降低批量关联风险
        if len(targets) > 1:
            delay = random.uniform(30, 90)
            print(f"等待 {delay:.0f}s 后处理下一账号...")
            time.sleep(delay)


if __name__ == "__main__":
    main()
