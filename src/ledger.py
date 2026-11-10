"""ledger: 积分账本 + 结算期冲刺提醒（v2 增强核心）

基于每 28 天一个结算期（周一 00:00 起）、达标积分 TARGET_POINTS=320 的机制：
- 每次运行把「已评歌曲数」「预计积分」追加写入 data/ledger/YYYY-MM-DD.jsonl
- 计算当前结算期（内置锚点 PERIOD_ANCHOR 起每 28 天自动滚动）内的累计已评歌曲与预计积分
- 输出距离达标线还差多少首歌（按约 3 分/首估算）
"""
import json
import os
from datetime import date, datetime, timedelta

LEDGER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ledger")

# 网易云「音乐合伙人」结算期锚点：74 期开始日 2026-11-09（周一）。
# 每 28 天一个周期，此后各期由代码自动滚动（75 期=2026-12-07、76 期=2027-01-04 …），无需配置。
PERIOD_ANCHOR = date(2026, 11, 9)

# 每期达标积分线（App 长期固定 320，若平台调整改这里即可，无需配置项）
TARGET_POINTS = 320


class Ledger:
    def __init__(self, name: str = "main"):
        self.name = name
        self.target = TARGET_POINTS
        os.makedirs(LEDGER_DIR, exist_ok=True)

    @staticmethod
    def _parse_date(s: str) -> date:
        return datetime.strptime(s, "%Y-%m-%d").date()

    @property
    def _file(self) -> str:
        return os.path.join(LEDGER_DIR, f"{self.name}.jsonl")

    def record(self, done: int, failed: int, note: str = ""):
        """记录一次运行结果（追加写入）"""
        row = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "done": done,
            "failed": failed,
            "note": note,
        }
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _rows(self) -> list:
        if not os.path.exists(self._file):
            return []
        rows = []
        with open(self._file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return rows

    def period_bounds(self, today: date = None) -> tuple:
        """返回当前结算期的 (开始日, 结束日)。按内置锚点每 28 天自动滚动。"""
        today = today or date.today()
        delta = (today - PERIOD_ANCHOR).days
        idx = delta // 28
        start = PERIOD_ANCHOR + timedelta(days=idx * 28)
        end = start + timedelta(days=27)
        return start, end

    def current_period_summary(self) -> dict:
        """当前结算期统计"""
        start, end = self.period_bounds()
        rows = self._rows()
        period_rows = [r for r in rows if start <= self._parse_date(r["ts"][:10]) <= end]
        done = sum(r.get("done", 0) for r in period_rows)
        failed = sum(r.get("failed", 0) for r in period_rows)
        # 简单估算：每评一首约 2~4 分，取中间值 3 分
        est_points = done * 3
        remaining = max(0, self.target - est_points)
        # 按最近完成的歌曲数估算还需几首（约 3 分/首）
        need_songs = -(-remaining // 3) if remaining > 0 else 0
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days_left": (end - date.today()).days,
            "done": done,
            "failed": failed,
            "est_points": est_points,
            "target": self.target,
            "remaining_points": remaining,
            "need_songs": need_songs,
        }

    def print_report(self):
        s = self.current_period_summary()
        lines = [
            f"===== 结算期报告 [{self.name}] =====",
            f"当前结算期: {s['start']} ~ {s['end']}（剩余 {s['days_left']} 天）",
            f"本期已评歌曲: {s['done']} 首（失败 {s['failed']}）",
            f"预计积分: ~{s['est_points']}（按 3分/首 估算）",
            f"达标线: {s['target']} 分",
        ]
        if s["remaining_points"] > 0:
            lines.append(f"还差约 {s['remaining_points']} 分 ≈ {s['need_songs']} 首歌（按 3分/首）")
        else:
            lines.append("✅ 已超过达标线，本期安全")
        return "\n".join(lines)
