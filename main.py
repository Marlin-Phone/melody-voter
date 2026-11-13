#!/usr/bin/env python3
"""melody-voter: 网易云音乐合伙人自动化助手

运行：python main.py            # 执行每日任务
      python main.py --report  # 查看当前结算期达标进度

配置：复制 config/setting.example.json 为 config/setting.json 并填写 Cookie
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from src.ledger import Ledger, TARGET_POINTS
from src.points import get_partner_points, query_pick_rights
from src.signer import ScoreEngine
from src.tasks import DailyTask, ExtraTask
from src.utils import Config, CookieValidator, Logger, Notifier


def _points_line(pts, target: int = TARGET_POINTS) -> str:
    """平台实际积分行（TG 报告用）；查询失败/None 返回空串"""
    if not pts or pts.get("integral") is None:
        return ""
    remaining = max(0, target - pts["integral"])
    return (
        f"平台实际积分: {pts['integral']} 分（{pts.get('title', '?')} 期{pts.get('period', '?')}，"
        f"{pts.get('status', '?')}）"
        f"，还差 {remaining} 分"
    )


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
        notifier.send(
            "melody-voter Cookie 失效，需重新扫码",
            f"{name}: {msg}\n\n"
            "请在本地运行 tools/login.py 扫码续命，\n"
            "并更新 Actions secret SETTING_JSON_B64",
        )
        return {"name": name, "error": msg}

    ledger = Ledger(name=name)

    # 2. 达标自动停止：本期积分 ≥ 达标线 → 不评分（防超额刷分触发风控）。
    #    新结算期平台清零后自动恢复，无需手动干预；积分查询失败时放行、不误停
    target = int(account.get("target_points", TARGET_POINTS))
    pts = get_partner_points(session, account.get("Cookie___csrf", ""), logger)
    cur = pts.get("integral") if pts else None
    if account.get("stop_at_target", True) and cur is not None and cur >= target:
        logger.info(f"[{name}] 本期积分 {cur}/{target} 已达标，自动停止评分（防超额刷分）")
        notifier.send(
            f"melody-voter [{name}] 已达标，自动跳过",
            f"平台实际积分 {cur}/{target} 已达标，本日不评分（stop_at_target）\n"
            f"新结算期积分清零后将自动恢复\n\n" + ledger.print_report(),
        )
        return {"name": name, "done": 0, "failed": 0, "skipped": "target_reached", "integral": cur}

    # 3. 同日去重（先探测、快速失败）：账本已有今天完成记录 -> 不再向平台提交。
    #    同日重复评分调用会被平台批量拒（制造风控信号且白白烧 15s/首 的等待）；
    #    首次 run 全部失败时 done=0，不影响失败后的当天重试
    done_today = ledger.today_done()
    if done_today > 0:
        logger.info(f"[{name}] 今天已有 {done_today} 首完成记录，跳过评分（防同日重复提交）")
        skip_body = (
            f"账本显示今天已完成 {done_today} 首（更早的 run），本次不重复提交平台\n\n"
            + ledger.print_report()
        )
        pts_line = _points_line(pts, target)
        if pts_line:
            skip_body = pts_line + "\n\n" + skip_body
        notifier.send(f"melody-voter [{name}] 今日已完成，跳过", skip_body)
        return {"name": name, "done": 0, "failed": 0, "skipped": True}

    # 4. 评分引擎（权重策略 + 评论）
    engine = ScoreEngine(
        weights=account.get("score_weights"),
        jitter=account.get("jitter", True),
    )
    pick_score = engine.pick_score
    tags_cb = engine.tags_for

    # 乐评选取：当日不重复（重复模板是官方「恶意刷分」条款 #2 的目标特征；
    # 池 32 条 ≥ 每日 20 条，正常轮不到重复，池耗尽时兜底随机）
    used_comments = set()

    def comment_cb():
        if not (account.get("enable_comment", True) and config["_comment_pool"]):
            return ""
        pool = config["_comment_pool"]
        unused = [c for c in pool if c not in used_comments]
        pick = random.choice(unused) if unused else random.choice(pool)
        used_comments.add(pick)
        return pick

    # 5. 基础任务
    daily = DailyTask(session, logger, config)
    complete, task_data = daily.get_tasks()
    if not complete and task_data.get("works"):
        daily_result = daily.run(pick_score, tags_cb, comment_cb)
    else:
        daily_result = {"type": "daily", "done": 0, "failed": 0, "id": str(task_data.get("id", ""))}

    # 6. 额外任务（使用每日任务 task_id，新协议需要）
    extra = ExtraTask(session, logger, config)
    try:
        extra_result = extra.run(
            pick_score, tags_cb, comment_cb, task_id=daily_result.get("id", "")
        )
    except Exception as e:
        logger.error(f"额外任务失败: {e}")
        extra_result = {"type": "extra", "done": 0, "failed": 0}

    # pick-right 诊断探针（只读、失败静默）：为「大众分一致性」策略攒样本
    pr = query_pick_rights(session, account.get("Cookie___csrf", ""), logger)
    if pr is not None:
        logger.info(f"pick-right 探针: {json.dumps(pr, ensure_ascii=False)[:500]}")

    total_done = daily_result.get("done", 0) + extra_result.get("done", 0)
    total_failed = daily_result.get("failed", 0) + extra_result.get("failed", 0)

    # 7. 记账 + 报告（结算期锚点与达标线均为 Ledger 内置常量，自动计算）
    if total_done or total_failed:
        ledger.record(total_done, total_failed, note="auto")
    logger.info(f"[{name}] 本次完成 {total_done} 首，失败 {total_failed} 首")
    logger.info(ledger.print_report())

    report_body = f"本次完成 {total_done} 首，失败 {total_failed} 首\n\n" + ledger.print_report()
    pts_line = _points_line(pts, target)
    if pts_line:
        report_body = pts_line + "\n\n" + report_body
    notifier.send(
        f"melody-voter [{name}] 每日报告 {(datetime.now() + timedelta(hours=8)):%Y-%m-%d}",
        report_body,
    )
    return {"name": name, "done": total_done, "failed": total_failed}


def notify_crash(acc: dict, exc: Exception):
    """运行抛异常时的 TG 兜底通知（python 层主动报，不依赖 workflow 失败邮件）"""
    try:
        cfg = Config()
        notifier = Notifier(cfg, Logger("crash"))
        notifier.send(
            f"melody-voter [{acc.get('name', '?')}] 运行异常",
            f"{type(exc).__name__}: {exc}",
        )
    except Exception as e2:
        print(f"异常通知也发送失败: {e2}")


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
            notify_crash(acc, e)
        # 账号间随机间隔，降低批量关联风险
        if len(targets) > 1:
            delay = random.uniform(30, 90)
            print(f"等待 {delay:.0f}s 后处理下一账号...")
            time.sleep(delay)


if __name__ == "__main__":
    main()
