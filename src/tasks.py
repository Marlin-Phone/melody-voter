"""tasks: 每日基础任务 + 额外评分任务（v2 增强：动态上限 / 评论 / 全量额外）"""
import random
import time
from typing import Dict, List, Tuple

from .signer import Signer, weapi_encrypt

API = {
    "daily_task": "https://interface.music.163.com/api/music/partner/daily/task/get",
    "extra_list": "https://interface.music.163.com/api/music/partner/extra/wait/evaluate/work/list",
    "report_listen": "https://interface.music.163.com/weapi/partner/resource/interact/report",
}


class DailyTask:
    """每日 5 首基础评分"""

    def __init__(self, session, logger, config: dict):
        self.session = session
        self.logger = logger
        self.config = config

    def get_tasks(self) -> Tuple[bool, dict]:
        resp = self.session.get(url=API["daily_task"], timeout=20).json()
        task_data = resp.get("data", {})
        count = task_data.get("count", 0)
        completed = task_data.get("completedCount", 0)
        self.logger.info(f"今日基础任务: [{completed}/{count}]")
        return (count == completed), task_data

    def run(self, engine, pick_score, tags_cb, comment_cb) -> dict:
        complete, task_data = self.get_tasks()
        result = {"type": "daily", "done": 0, "failed": 0, "id": task_data.get("id", "")}
        if complete or not task_data.get("works"):
            self.logger.info("基础任务已全部完成")
            return result

        signer = Signer(
            self.session,
            task_data["id"],
            self.logger,
            {
                **self.config,
                "_pick_score_cb": lambda: pick_score(),
                "_tags_cb": tags_cb,
                "_comment_cb": comment_cb,
            },
            debug=self.config.get("_debug", False),
        )
        for task in task_data.get("works", []):
            work = task.get("work", {})
            if task.get("completed"):
                self.logger.info(f'「{work.get("name")}」已有评分：{task.get("score")}分')
                continue
            ok, _ = signer.sign(work)
            if ok:
                result["done"] += 1
            else:
                result["failed"] += 1
        return result


class ExtraTask:
    """额外评分任务（v2：动态读取上限，可做满全部）"""

    def __init__(self, session, logger, config: dict):
        self.session = session
        self.logger = logger
        self.config = config

    def get_extra_tasks(self) -> Tuple[List[dict], int]:
        resp = self.session.get(
            url=API["extra_list"], headers={"Referer": "https://mp.music.163.com/"}, timeout=20
        ).json()
        if resp.get("code") != 200:
            raise RuntimeError(f"获取额外任务失败: {resp.get('message', '未知错误')}")
        tasks = resp.get("data", [])
        uncompleted = [t for t in tasks if not t.get("completed")]
        completed_count = len([t for t in tasks if t.get("completed")])
        return uncompleted, completed_count

    def run(self, engine, pick_score, tags_cb, comment_cb, task_id: str = "") -> dict:
        if not task_id:
            # 额外任务无 taskId 也能上报听歌；评分走空 taskId（与原脚本一致）
            pass
        result = {"type": "extra", "done": 0, "failed": 0}

        uncompleted, completed_count = self.get_extra_tasks()
        limit = int(self.config.get("extra_task_limit", 0) or 0)
        if limit <= 0:
            limit = len(uncompleted) + completed_count  # 动态上限=做满当前全部
        remaining = max(0, limit - completed_count)
        if remaining <= 0:
            self.logger.info(f"额外任务已完成 {completed_count}，达到上限 {limit}")
            return result

        self.logger.info(f"待完成额外评分: {len(uncompleted)} 个（本轮上限 {limit}，已完成 {completed_count}）")

        signer = Signer(
            self.session,
            "",
            self.logger,
            {
                **self.config,
                "_pick_score_cb": lambda: pick_score(),
                "_tags_cb": tags_cb,
                "_comment_cb": comment_cb,
            },
            debug=self.config.get("_debug", False),
        )

        done_in_this_run = 0
        for task in uncompleted:
            if done_in_this_run >= remaining:
                break
            work = task.get("work", {})
            try:
                self._report_listen(work)
                ok, _ = signer.sign(work, is_extra=True)
                if ok:
                    result["done"] += 1
                    done_in_this_run += 1
                else:
                    result["failed"] += 1
                delay = random.uniform(
                    self.config.get("wait_time_min", 15),
                    self.config.get("wait_time_max", 20),
                )
                time.sleep(delay)
            except Exception as e:
                self.logger.warning(f'处理「{work.get("name")}」失败: {e}')
                result["failed"] += 1
                continue
        self.logger.info(f"额外评分任务完成: 本次 {result['done']} 个")
        return result

    def _report_listen(self, work: dict):
        """上报听歌记录（评分的先决条件）"""
        csrf = self.session.cookies.get("__csrf", "")
        data = {
            "workId": work["id"],
            "resourceId": work.get("resourceId", ""),
            "bizResourceId": "",
            "interactType": "PLAY_END",
            "csrf_token": csrf,
        }
        params = weapi_encrypt(data)
        resp = self.session.post(
            url=f"{API['report_listen']}?csrf_token={csrf}",
            data=params,
            headers={"Referer": "https://mp.music.163.com/"},
            timeout=20,
        ).json()
        if resp.get("code") != 200:
            self.logger.warning(f"听歌上报异常: {resp.get('message', resp.get('msg', ''))}")
        else:
            self.logger.debug("听歌记录上报成功")