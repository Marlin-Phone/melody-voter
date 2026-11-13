"""points: 平台实际积分实时查询

端点来源：网易云音乐合伙人 Web 端（mp.music.163.com）接口，参考开源项目
crossgg/netease-cloud-music api/weapi/partner.go（HAR 抓包生成）：
  - /weapi/music/partner/user/info/get   当前积分/等级/状态（integral/title/status）
  - /weapi/music/partner/home/get        本期积分 + 本周积分
只读查询，失败返回 None，不影响主流程。
"""
from .signer import weapi_encrypt

USER_INFO_URL = "https://interface.music.163.com/weapi/music/partner/user/info/get"
HOME_URL = "https://interface.music.163.com/weapi/music/partner/home/get"
REFERER = "https://mp.music.163.com/"


def get_partner_points(session, csrf: str, logger=None) -> dict:
    """查询平台实际积分。成功返回 dict（integral/title/status/period/...），失败返回 None。"""

    def _post(url: str) -> dict:
        params = weapi_encrypt({"csrf_token": csrf})
        return session.post(
            f"{url}?csrf_token={csrf}",
            data=params,
            headers={"Referer": REFERER},
            timeout=20,
        ).json()

    try:
        info = _post(USER_INFO_URL)
        home = _post(HOME_URL)
        if info.get("code") != 200:
            raise RuntimeError(f"user/info code={info.get('code')} msg={info.get('message', info.get('msg', ''))}")
        d = info.get("data") or {}
        h = home.get("data") or {}
        return {
            "integral": d.get("integral"),                # 本期实际积分（App「我的记录」同源）
            "current_week": (h.get("integral") or {}).get("currentWeekIntegral"),
            "period": h.get("period"),
            "title": d.get("title"),                      # JUNIOR/SENIOR
            "status": d.get("status"),                    # NORMAL/ELIMINATED
            "evaluate_count": d.get("evaluateCount"),    # 累计测评数
        }
    except Exception as e:
        if logger:
            logger.warning(f"平台积分查询失败（不影响主流程）: {e}")
        return None
