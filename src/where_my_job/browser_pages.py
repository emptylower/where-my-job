"""开工前"专用浏览器里只有空白页"的共同判定。
launcher 用 /json/list 预检（不建立会话、不占额度），adapter 在建会话时兜底。
两条路径必须用同一份判定，否则预检放行、建会话时才拒绝，额度照样被消耗。"""
from __future__ import annotations
from .errors import EnvError
from .public_messages import public_message
from .redact import redact_url

BLANK_URLS = ("about:blank", "chrome://newtab/", "chrome://new-tab-page/")
MAX_OPEN_PAGES = 8
NOT_BLANK_NEXT = ("先运行 where-my-job browser stop，再运行 where-my-job init --browser，然后重试本次命令；"
                  "登录状态保存在专用 profile 里，不会因此丢失")

def extra_pages(targets, allow_target_id: str | None = None) -> list[dict]:
    """挑出不该存在的标签页。
    注意标识字段有两种拼法：HTTP /json/list 用 id，CDP Target.getTargets 用 targetId，两者都要认，
    否则 allow_target_id 永远匹配不上，正在进行的扫码登录会被自己的预检拒绝。"""
    out: list[dict] = []
    for t in targets:
        if not isinstance(t, dict) or t.get("type") != "page" or t.get("url") in BLANK_URLS:
            continue
        if allow_target_id is not None and (t.get("targetId") or t.get("id")) == allow_target_id:
            continue
        out.append(t)
    return out

def not_blank_error(pages: list[dict]) -> EnvError:
    """多余标签页以脱敏地址交回，供 agent 告诉用户要关掉什么；不含参数值。"""
    urls = [redact_url(str(p.get("url") or "")) for p in pages[:MAX_OPEN_PAGES]]
    return EnvError("BROWSER_NOT_BLANK", public_message("BROWSER_NOT_BLANK"),
                    data={"browser": {"open_pages": urls, "next_step": NOT_BLANK_NEXT}})
