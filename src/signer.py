"""signer: 网易云 weapi 加密签名 + 评分策略引擎（v3 适配新协议）"""
import base64
import codecs
import json
import random
import time
from typing import Dict, Tuple

from Crypto.Cipher import AES

PUB_KEY = "010001"
MODULUS = "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
IV = "0102030405060708"
AES_KEY = "0CoJUm6Qyw8W8jud"


def _add_to_16(text: str) -> bytes:
    """按 UTF-8 字节数填充到 16 的倍数（中文 3 字节，不能按字符数算）"""
    data = text.encode("utf-8")
    pad = 16 - len(data) % 16
    return data + bytes([pad] * pad)


def weapi_encrypt(data: dict) -> Dict[str, str]:
    """生成 weapi 请求的 params / encSecKey"""
    random_str = "".join(
        random.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        for _ in range(16)
    )

    def aes_encrypt(text: str, key: str) -> str:
        cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, IV.encode("utf-8"))
        return base64.b64encode(cipher.encrypt(_add_to_16(text))).decode("utf-8")

    # ensure_ascii=True：中文转义为 \uXXXX，避免编码长度与字符数不一致
    params = aes_encrypt(json.dumps(data, ensure_ascii=True), AES_KEY)
    params = aes_encrypt(params, random_str)

    rev = random_str[::-1]
    rs = int(codecs.encode(rev.encode("utf-8"), "hex_codec"), 16)
    enc = pow(rs, int(PUB_KEY, 16), int(MODULUS, 16))
    enc_sec_key = format(enc, "x").zfill(256)
    return {"params": params, "encSecKey": enc_sec_key}


class ScoreEngine:
    """
    评分策略引擎（对应 2026-09 机制改动）
    - weights: {1: x, 2: x, 3: x, 4: x, 5: x} 权重（百分比或权重值）
    - 新映射规则下"好听5星、难听1星"才准，全部中庸分（3-4）准确率仅 ~20%
      因此默认拉高 4/5 星权重，1/2 星保留少量（模拟正态/随机）
    - 支持两档抖动：主流分 + 5% 概率贴近正态分布的评分，降低被风控识别为脚本
    """

    def __init__(self, weights: dict = None, jitter: bool = True):
        if weights is None:
            weights = {"1": 5, "2": 10, "3": 15, "4": 30, "5": 40}
        self.weights = {int(k): float(v) for k, v in weights.items()}
        self.jitter = jitter
        self._cache_norm()

    def _cache_norm(self):
        total = sum(self.weights.values())
        self._pool = []
        for score, weight in self.weights.items():
            self._pool.extend([score] * max(1, int(weight / total * 100)))
        # 兜底：若池子过小
        while len(self._pool) < 20:
            self._pool.extend(list(self.weights.keys()))

    def pick_score(self) -> int:
        score = random.choice(self._pool)
        if self.jitter and random.random() < 0.05:
            # 5% 概率改为 1-5 随机，避免长期分布过于一致
            score = random.randint(1, 5)
        return int(score)

    def tags_for(self, score: int) -> str:
        # 保持与原脚本一致的 tags 格式（如 5-A-1），后续可扩展为 "旋律/歌词" 小评分
        return f"{score}-A-1"

    def comment_for(self, pool: list) -> str:
        return random.choice(pool) if pool else ""


class Signer:
    def __init__(self, session, task_id: str, logger, config: dict, debug: bool = False):
        self.session = session
        self.task_id = task_id
        self.logger = logger
        self.config = config
        self.debug = debug
        self.sign_url = "https://interface.music.163.com/weapi/music/partner/work/evaluate"

    def sign(self, work: dict, is_extra: bool = False, extra_score: str = "{}") -> Tuple[bool, dict]:
        """
        评分并返回 (是否成功, 响应体)
        extra_score: 小评分维度 JSON 字符串，如 '{"2":4,"3":5}'（新协议必需）
        """
        try:
            delay = random.uniform(
                self.config.get("wait_time_min", 10),
                self.config.get("wait_time_max", 20),
            )
            self.logger.debug(f"评分前等待 {delay:.1f}s")
            time.sleep(delay)

            csrf = str(self.session.cookies.get("__csrf", ""))
            score = int(self.config["_pick_score_cb"]()) if callable(
                self.config.get("_pick_score_cb")
            ) else int(self.config.get("score", 5))
            tags = self.config["_tags_cb"](score) if callable(
                self.config.get("_tags_cb")
            ) else f"{score}-A-1"
            comment = self.config["_comment_cb"]() if callable(
                self.config.get("_comment_cb")
            ) else ""

            data = {
                "taskId": self.task_id,
                "workId": work["id"],
                "score": str(score),
                "tags": tags,
                "customTags": "[]",
                "comment": comment,
                "syncYunCircle": "true",
                "syncComment": "true" if comment else "false",
                "extraScore": extra_score,
                "source": "mp-music-partner",
                "csrf_token": csrf,
            }
            if is_extra:
                data["extraResource"] = "true"

            params = weapi_encrypt(data)
            resp = self.session.post(
                url=f"{self.sign_url}?csrf_token={csrf}", data=params, timeout=20
            ).json()

            if self.debug:
                self.logger.debug(f"评分响应[{work.get('name')}]: {resp}")

            code = resp.get("code")
            if code == 200:
                self.logger.info(
                    f'「{work.get("name")}」{work.get("authorName")} 评分完成：{score}分'
                )
                return True, resp
            msg = resp.get("message") or resp.get("msg") or "未知错误"
            if "频繁" in msg:
                self.logger.warning("频率限制，等待后重试")
                time.sleep(random.uniform(30, 60))
                return self.sign(work, is_extra, extra_score)
            if code == 405 and "资源状态异常" in msg:
                self.logger.warning(f'「{work.get("name")}」资源状态异常，跳过')
                return False, resp
            # 今日配额已满（'今日没有更多可评定歌曲啦' 等 405）——整体跳过不重试
            if code == 405 and "没有更多" in str(msg):
                self.logger.info("今日评分配额已满，停止本轮评分")
                return False, resp
            self.logger.error(f"评分失败: {msg} (code={code})")
            return False, resp
        except Exception as e:
            self.logger.error(f'「{work.get("name")}」评分异常: {e}')
            return False, {"error": str(e)}