# 本文件由子计划 05 Task 1 的抽取脚本生成：逐字复制 boss-zhipin-scraper@eb5a8e64
# scripts/boss_cdp_raw.py 中的 32 个顶层对象。不得手工修改；来源行号与逐段 SHA256 见 UPSTREAM.md。
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl


DEFAULT_CDP_PORT = 9222


API_JOB_LIST_PATH = "/wapi/zpgeek/search/joblist.json"


PROBE_CAPTURE_TIMEOUT = 25


LOGIN_RESTRICTED_CODES = {31, 37}


LOGIN_RESTRICTED_MESSAGE_KEYWORDS = (
    "环境存在异常",
    "访问频繁",
    "操作太频繁",
    "安全校验",
    "滑块",
    "验证",
)


SCALE_MAP = {
    "0-20人": "301", "20-99人": "302", "100-499人": "303",
    "500-999人": "304", "1000-9999人": "305", "10000人以上": "306",
}


STAGE_MAP = {
    "未融资": "801", "天使轮": "802", "A轮": "803", "B轮": "804",
    "C轮": "805", "D轮及以上": "806", "已上市": "807", "不需要融资": "808",
}


SALARY_MAP = {
    "不限": "0", "3K以下": "402", "3-5K": "403", "5-10K": "404",
    "10-20K": "405", "20-50K": "406", "50K以上": "407",
}


EXPERIENCE_MAP = {
    "不限": "0", "在校生": "108", "应届生": "102", "经验不限": "101",
    "1年以内": "103", "1-3年": "104",
    "3-5年": "105", "5-10年": "106", "10年以上": "107",
}


DEGREE_MAP = {
    "不限": "0", "初中及以下": "209", "中专/中技": "208", "高中": "206",
    "大专": "202", "本科": "203", "硕士": "204", "博士": "205",
}


INDUSTRY_MAP = {
    "互联网": "1001", "电子商务": "1002", "金融": "1003", "游戏": "1004",
    "企业服务": "1005", "教育培训": "1006", "社交网络": "1007",
    "医疗健康": "1008", "生活服务": "1009", "广告营销": "1010",
}


def map_api_job(raw):
    """把 joblist.json 原始条目映射为统一的 job 字典（原注入 JS 模板逻辑的 Python 版）。"""
    if not isinstance(raw, dict):
        return None

    encrypt_job_id = str(raw.get("encryptJobId") or "")
    encrypt_brand_id = str(raw.get("encryptBrandId") or "")
    return {
        "title": raw.get("jobName") or "",
        "salary": raw.get("salaryDesc") or "",
        "salary_source": "api" if raw.get("salaryDesc") else "api_empty",
        "location": "\u00b7".join([
            raw.get("cityName") or "",
            raw.get("areaDistrict") or "",
            raw.get("businessDistrict") or "",
        ]),
        "tags": " | ".join(
            t for t in (raw.get("jobExperience") or "", raw.get("jobDegree") or "")
            if t and t != "不限"
        ),
        "boss_name": raw.get("brandName") or "",
        "boss_title": raw.get("bossTitle") or "",
        "boss_active_status": map_list_boss_active_status(raw),
        "company_scale": raw.get("brandScaleName") or "",
        "company_stage": raw.get("brandStageName") or "",
        "company_industry": raw.get("brandIndustry") or "",
        "job_labels": " | ".join(raw.get("jobLabels") or []),
        "skills": " | ".join(raw.get("skills") or []),
        "security_id": raw.get("securityId") or "",
        "lid": raw.get("lid") or "",
        "encrypt_job_id": encrypt_job_id,
        "encrypt_boss_id": str(raw.get("encryptBossId") or ""),
        "encrypt_brand_id": encrypt_brand_id,
        "job_link": (
            f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html"
            if encrypt_job_id else ""
        ),
        "company_link": (
            f"https://www.zhipin.com/gongsi/{encrypt_brand_id}.html"
            if encrypt_brand_id else ""
        ),
        "welfare": " | ".join(raw.get("welfareList") or []),
    }


def map_api_jobs(data):
    """从捕获的 joblist 响应 JSON 提取映射后的职位列表。"""
    if not isinstance(data, dict):
        return []
    job_list = (data.get("zpData") or {}).get("jobList")
    if not isinstance(job_list, list):
        return []
    return [j for j in (map_api_job(item) for item in job_list) if j]


DETAIL_LOGIN_MARKER = "登录查看完整内容"


DETAIL_DESCRIPTION_MARKER = "职位描述"


DETAIL_COMPETITIVENESS_MARKER = "竞争力分析"


DETAIL_SAFETY_MARKER = "BOSS 安全提示"


MIN_DETAIL_TEXT_LENGTH = 120


class DetailExtractionError(ValueError):
    """The rendered page does not contain a usable job description."""


class DetailLoginRequiredError(DetailExtractionError):
    """The detail page is truncated because the BOSS session is not logged in."""


EXTRACT_DETAIL_JS = """
(function(){
    var pageText = document.body ? document.body.innerText : '';
    var tags = [];
    var benefitWords = ['五险','补充医疗','定期体检','带薪年假','年终奖','零食','餐补',
        '节日福利','加班补助','股票期权','员工旅游','交通补助','通讯补贴','团建',
        '生日福利','免费班车','全勤奖','包吃','弹性工作','下午茶','租房补贴',
        '体检','健身','文化','充电假','司龄假','红包','能量补贴','社团','三薪',
        '绩效','底薪','保底','活动基金','学习基金','节日礼品','无障碍'];
    var noiseWords = ['BOSS直聘','boss','BOSS','来自BOSS直聘','金','金币'];
    function isBenefit(t) {
        if (t === '...' || t.length > 15 || t.length < 2) return true;
        for (var i = 0; i < benefitWords.length; i++) {
            if (t.includes(benefitWords[i])) return true;
        }
        for (var i = 0; i < noiseWords.length; i++) {
            if (t === noiseWords[i] || t.includes(noiseWords[i])) return true;
        }
        return false;
    }
    document.querySelectorAll('.job-tags .tag-all span, .job-keyword-list span').forEach(function(s){
        var t = s.innerText.trim();
        if(t && !isBenefit(t)) tags.push(t);
    });
    var jd = '';
    var sections = document.querySelectorAll('.job-detail-section, .job-sec');
    for (var i = 0; i < sections.length; i++) {
        var text = (sections[i].innerText || '').trim();
        if (text.indexOf('职位描述') !== -1 && text.length > jd.length) {
            jd = text;
        }
    }
    return JSON.stringify({
        jd: jd,
        page_text: pageText.substring(0, 12000),
        tags: tags,
        url: location.href
    });
})()
"""


def _normalize_detail_whitespace(text):
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").splitlines()]
    normalized = "\n".join(lines).strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return re.sub(r"[ \t]{2,}", " ", normalized)


def _looks_like_navigation_page(text):
    return (
        DETAIL_DESCRIPTION_MARKER not in text
        and "无障碍专区" in text
        and "首页" in text
        and "职位" in text
        and "公司" in text
    )


def _is_boss_activity_line(text):
    """True for recruiter activity labels like「在线」「今日活跃」."""
    return text == "在线" or text.endswith("活跃")


def map_list_boss_active_status(job):
    """Map list-API job fields to ``boss_active_status``.

    BOSS ``/wapi/zpgeek/search/joblist.json`` typically exposes ``bossOnline``
    but not ``activeTimeDesc``. Prefer ``activeTimeDesc`` when present;
    otherwise map ``bossOnline=True`` to 「在线」. Detailed labels such as
    「刚刚活跃」still come from the detail path.
    """
    if not isinstance(job, dict):
        return ""
    desc = str(job.get("activeTimeDesc") or "").strip()
    if desc:
        return desc
    if job.get("bossOnline"):
        return "在线"
    return ""


def _recruiter_footer_info(lines):
    """Locate recruiter card footer and optional activity status.

    Returns ``(footer_start, boss_active_status)``. ``footer_start`` is the
    line index where the recruiter card begins (to truncate JD), or ``None``.
    ``boss_active_status`` is e.g. ``今日活跃`` / ``在线``, or ``""``.
    """
    stripped_lines = [line.strip() for line in lines]
    end = len(stripped_lines)
    while end and not stripped_lines[end - 1]:
        end -= 1

    def card_info(card_end):
        while card_end and not stripped_lines[card_end - 1]:
            card_end -= 1
        if card_end < 4 or stripped_lines[card_end - 2] != "·":
            return None, ""
        activity_or_name = stripped_lines[card_end - 4]
        has_activity_line = _is_boss_activity_line(activity_or_name)
        if has_activity_line:
            start = card_end - 5
            status = activity_or_name
        else:
            start = card_end - 4
            status = ""
        if start < 0:
            return None, ""
        return start, status

    for marker in (DETAIL_COMPETITIVENESS_MARKER, DETAIL_SAFETY_MARKER):
        try:
            marker_index = stripped_lines.index(marker)
        except ValueError:
            continue
        start, status = card_info(marker_index)
        if start is not None:
            return start, status
    return card_info(end)


def extract_detail_fields(extracted, min_length=MIN_DETAIL_TEXT_LENGTH):
    """Return validated JD and boss activity status as separate fields.

    ``jd`` never includes the recruiter card or activity label.
    ``boss_active_status`` is extracted from that card when present.

    ``page_text`` is diagnostic input only. It is never persisted unless it has
    an explicit job-description section that passes all checks.
    """
    if not isinstance(extracted, dict):
        raise DetailExtractionError("detail extractor returned non-dict")

    raw_jd = str(extracted.get("jd") or "")
    page_text = str(extracted.get("page_text") or "")
    diagnostic_text = "\n".join((raw_jd, page_text))

    if DETAIL_LOGIN_MARKER in diagnostic_text:
        raise DetailLoginRequiredError(
            "detail page is truncated at the login wall; refresh the BOSS login session"
        )
    if _looks_like_navigation_page(diagnostic_text):
        raise DetailExtractionError("detail page rendered navigation chrome without a JD")

    text = raw_jd
    if not text and DETAIL_DESCRIPTION_MARKER in page_text:
        text = page_text
    if DETAIL_DESCRIPTION_MARKER in text:
        text = text.split(DETAIL_DESCRIPTION_MARKER, 1)[1]

    lines = text.replace("\r\n", "\n").splitlines()
    footer_start, boss_active_status = _recruiter_footer_info(lines)
    if footer_start is not None:
        lines = lines[:footer_start]
    else:
        for index, line in enumerate(lines):
            if line.strip() == DETAIL_SAFETY_MARKER:
                lines = lines[:index]
                break

    jd = _normalize_detail_whitespace("\n".join(lines))
    if len(jd) < min_length:
        raise DetailExtractionError(
            f"job description too short after validation: {len(jd)} < {min_length}"
        )
    return {"jd": jd, "boss_active_status": boss_active_status}


def extract_job_description(extracted, min_length=MIN_DETAIL_TEXT_LENGTH):
    """Return validated JD text without BOSS page chrome."""
    return extract_detail_fields(extracted, min_length=min_length)["jd"]


class LoginProbeStatus(Enum):
    """Outcome of one login probe request."""

    AVAILABLE = "available"
    UNAUTHENTICATED = "unauthenticated"
    RESTRICTED = "restricted"
    EMPTY = "empty"
    RESPONSE_ERROR = "response_error"


@dataclass(frozen=True)
class LoginProbeResult:
    """Structured login probe result with the original failure context."""

    status: LoginProbeStatus
    code: int | None = None
    message: str = ""
    retryable: bool = False


def classify_login_probe_response(data, http_status=200):
    """Classify a BOSS search response without collapsing failures to bool."""
    if http_status == 401:
        return LoginProbeResult(
            LoginProbeStatus.UNAUTHENTICATED,
            message="HTTP 401",
        )
    if http_status in (403, 429):
        return LoginProbeResult(
            LoginProbeStatus.RESTRICTED,
            message=f"HTTP {http_status}",
        )
    if http_status != 200:
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR,
            message=f"HTTP {http_status}",
            retryable=http_status == 0 or http_status >= 500,
        )
    if not isinstance(data, dict):
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR,
            message="响应不是 JSON 对象",
            retryable=True,
        )

    raw_code = data.get("code")
    try:
        code = int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        code = None
    message = str(data.get("message") or data.get("msg") or "")

    if code in LOGIN_RESTRICTED_CODES:
        return LoginProbeResult(LoginProbeStatus.RESTRICTED, code=code, message=message)
    if code != 0:
        # code 不在已知风控码集合里时，再按 message 关键字兜底判定是否风控，
        # 避免新风控码被当成不可恢复的 RESPONSE_ERROR 误拦已登录用户。
        if any(kw in message for kw in LOGIN_RESTRICTED_MESSAGE_KEYWORDS):
            return LoginProbeResult(LoginProbeStatus.RESTRICTED, code=code, message=message)
        return LoginProbeResult(LoginProbeStatus.RESPONSE_ERROR, code=code, message=message)

    zp_data = data.get("zpData")
    if not isinstance(zp_data, dict):
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR,
            code=code,
            message="响应缺少 zpData",
            retryable=True,
        )
    job_list = zp_data.get("jobList")
    if not isinstance(job_list, list):
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR,
            code=code,
            message="响应缺少 jobList",
            retryable=True,
        )
    if not job_list:
        return LoginProbeResult(LoginProbeStatus.EMPTY, code=code)
    if any(
        (job.get("salaryDesc") or "").strip()
        for job in job_list
        if isinstance(job, dict)
    ):
        return LoginProbeResult(LoginProbeStatus.AVAILABLE, code=code)
    return LoginProbeResult(LoginProbeStatus.UNAUTHENTICATED, code=code)


def build_search_url(keyword, city_code, page, filters):
    params = {"query": keyword, "city": city_code, "page": page}
    for key, code in filters.items():
        if code:
            params[key] = code
    return f"https://www.zhipin.com/web/geek/job?{urlencode(params)}"
