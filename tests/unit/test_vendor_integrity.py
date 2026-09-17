"""vendor 是上游 32 个顶层对象的逐字副本：顺序、每段文本 SHA256、导入行都固定。"""
import ast, hashlib, os, pathlib, re
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
V = ROOT / "src" / "where_my_job" / "vendor" / "boss_zhipin_scraper"
UPSTREAM_COMMIT = "eb5a8e646d4e4bfc024cf53f2a5b543ad8d75edc"
UPSTREAM_FILE_SHA256 = "2d28e3a1915d20fff031b8b79eeffff9c0e815f40ee2d5ef217a3b2d73a6a91f"
FIXED_IMPORTS = [
    "import re",
    "from dataclasses import dataclass",
    "from enum import Enum",
    "from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl",
]
# (名称, 上游起始行, 上游结束行, 该段原文 SHA256)；起始行含装饰器
EXPECTED = [
    ("DEFAULT_CDP_PORT", 72, 72, "8fbe85ed0c44a483b121aac29b335611ea43b4bc9eadb64febdae532fee95e4e"),
    ("API_JOB_LIST_PATH", 75, 75, "164c7ae978b72e27223b0102564d42dfb38d6e69cebc2a3e75a90f0bf8cca98f"),
    ("PROBE_CAPTURE_TIMEOUT", 197, 197, "74202c0fcc3e9e4599ebe579b93a222e343cf677dce6c9796d8bbc94c80810a8"),
    ("LOGIN_RESTRICTED_CODES", 198, 198, "2f28f96fe35dfab450fa791c145af2527196b9ee70591153fe3b6f485ac46f98"),
    ("LOGIN_RESTRICTED_MESSAGE_KEYWORDS", 201, 208, "8e3a1c65566a389335543650c2665b394daa8ba05df2082f04d6710ef6afd81f"),
    ("SCALE_MAP", 310, 313, "77ff48d58cea97929d0e89b0f6e44c6d37f7ffeae8dfbf437ef0827da8c10321"),
    ("STAGE_MAP", 315, 318, "fd3726771fae0b0dd0589e916abceadb9afa91874f3fe533064e16c44d450eae"),
    ("SALARY_MAP", 320, 323, "40c1ca5b51d6e9160b61a8adda6426675794324e07892ba49ee5a88690900edb"),
    ("EXPERIENCE_MAP", 325, 329, "8151464f715633e3f90364bb95302662e9c1e49e96d62defe3a7f18c6048b457"),
    ("DEGREE_MAP", 331, 334, "a58dc86986bc803033498564dfdc4e1445433704d41c166f7692474dec1449b0"),
    ("INDUSTRY_MAP", 336, 340, "cbdd5218e2228771f7e0b4d6107c142623ad1bea5bee6305840833bc83877ffd"),
    ("map_api_job", 599, 641, "ce69016082f62ab1d96b0f53e932fa7fe60b7c3c90a30a3b7d5aeed06078f0fb"),
    ("map_api_jobs", 644, 651, "9683beac37118912146d23d01c1ae9d37d7460ee1e6e541872d92ce8a3b743e9"),
    ("DETAIL_LOGIN_MARKER", 696, 696, "1058c2dc086366e7a8ecd4b2b1ff34dd2a7e1f7b5d30b048ba3f8e459067b3b1"),
    ("DETAIL_DESCRIPTION_MARKER", 697, 697, "9e6bff48b2df0e5b22a6385b4c6472113ba1ad99b1a0ab4b6672809bcab6dc98"),
    ("DETAIL_COMPETITIVENESS_MARKER", 698, 698, "e37381d8ab37320f31fe9a5322845775ab80bd181c16cb9660e76dcda2d9a9eb"),
    ("DETAIL_SAFETY_MARKER", 699, 699, "9551d08e9b3a7547a1ad73603290595a4b6639ad38ed6d9426ad025d818ca867"),
    ("MIN_DETAIL_TEXT_LENGTH", 700, 700, "733d3ac640fa5462deebee0ebdd686a52de7e3a9f14fcb8d4ea932afe3401425"),
    ("DetailExtractionError", 703, 704, "d5bbac9609948bd6ceeac7143c66134c8c457456f9f09ab1f4d5e38693600583"),
    ("DetailLoginRequiredError", 707, 708, "e1b967407a4e4491ac1d913d7ec72b46de2e8c79146db324f180565f12e25e26"),
    ("EXTRACT_DETAIL_JS", 711, 750, "27fe3cfd1aec7802a55b3d313d1c8f9379a14be20b54a862856250d88b04c4c1"),
    ("_normalize_detail_whitespace", 753, 757, "9e2523c075a40cbc2c520c62202bfbf563e7f40a993eb87f70953bbbbea3281d"),
    ("_looks_like_navigation_page", 760, 767, "9f6cfcd8baba691d0ba2e171f078085f24f03f6fdd0a78231c4927db4800d82c"),
    ("_is_boss_activity_line", 770, 772, "160434cb9a9068bc88412169b91ae37d2bea60517db9b1583a47f2582e20b09c"),
    ("map_list_boss_active_status", 775, 790, "97a7cf624596f546227954446df9f10258ff45f5588b2f762d22ec323d95ee15"),
    ("_recruiter_footer_info", 801, 838, "c661928ad863c55f5567279e1d7e77c0da9901bc27c8b065ca2e243703c5938e"),
    ("extract_detail_fields", 846, 890, "731966b1debc78f3cede42b70b553ab6f9ffe45105147f05785d46c58bd381ea"),
    ("extract_job_description", 893, 895, "34f47c5eec99601264eaff0b32f1d25ac2985fc12686423f3fd0973837c61d07"),
    ("LoginProbeStatus", 1027, 1034, "9df071a88b5431f7f1809cd98a6f737454a6f6b48f02f61cb11cb32ed9ed474c"),
    ("LoginProbeResult", 1037, 1044, "f0fd5966ab8fd768fc9738ed14a573d0daf629b01fc58c4fc2b2b31006e3c0a2"),
    ("classify_login_probe_response", 1047, 1112, "a478b5a9219a2d5018fd1876c153392b5024ddc3a4315f0cc991b94259d5be43"),
    ("build_search_url", 1442, 1447, "a499a2f57480ac1c67147383df5b8953f64c54b5f79a443d5c5cdc1437562081"),
]

def _node_name(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None

def _snippets(text: str) -> list[tuple[str, int, int, str]]:
    lines = text.splitlines(keepends=True)
    out = []
    for node in ast.parse(text).body:
        name = _node_name(node)
        if name is None:
            continue
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        body = "".join(lines[start - 1:node.end_lineno])
        out.append((name, start, node.end_lineno, hashlib.sha256(body.encode("utf-8")).hexdigest()))
    return out

def test_primitives_is_exact_ordered_copy():
    text = (V / "primitives.py").read_text(encoding="utf-8")
    got = _snippets(text)
    assert [g[0] for g in got] == [e[0] for e in EXPECTED]
    assert [g[3] for g in got] == [e[3] for e in EXPECTED]

def test_primitives_has_only_fixed_imports_and_copied_objects():
    text = (V / "primitives.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = [ast.get_source_segment(text, n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert imports == FIXED_IMPORTS
    others = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom)) and _node_name(n) is None]
    assert others == []

def test_upstream_md_records_commit_file_hash_and_every_snippet():
    md = (V / "UPSTREAM.md").read_text(encoding="utf-8")
    assert UPSTREAM_COMMIT in md and UPSTREAM_FILE_SHA256 in md
    rows = re.findall(r"^\| `([A-Za-z_]+)` \| L(\d+)–L(\d+) \| `([0-9a-f]{64})` \|", md, re.M)
    assert [(n, int(a), int(b), h) for n, a, b, h in rows] == EXPECTED

def test_against_real_upstream_file_when_present():
    path = pathlib.Path(os.environ.get("WMJ_UPSTREAM_BOSS_CDP_RAW",
                                       "~/Desktop/boss-hunter-handoff/vendor-boss-zhipin-scraper/scripts/boss_cdp_raw.py")).expanduser()
    if not path.exists():
        pytest.skip("上游原文件不在本机；仅在维护者机器上核对")
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == UPSTREAM_FILE_SHA256
    by_name = {n: (a, b, h) for n, a, b, h in _snippets(data.decode("utf-8"))}
    for name, start, end, digest in EXPECTED:
        assert by_name[name] == (start, end, digest), name

def test_vendor_has_no_runners_sessions_or_network():
    src = (V / "primitives.py").read_text(encoding="utf-8")
    for banned in ("class CDPSession", "NetworkJoblistCapture", "def run_setup_chrome", "def scrape_details",
                   "EXTRACT_LIST_JS", "remote-allow-origins", "urlopen(", "import websocket", "import requests",
                   "def main", "subprocess"):
        assert banned not in src

def test_vendor_objects_behave():
    from where_my_job.vendor.boss_zhipin_scraper import primitives as p
    r = p.classify_login_probe_response({"code": 37, "message": "x", "zpData": None})
    assert r.status is p.LoginProbeStatus.RESTRICTED and r.code == 37
    assert p.build_search_url("AI", "101220100", 2, {"salary": "405"}).endswith("query=AI&city=101220100&page=2&salary=405")
    jobs = p.map_api_jobs({"zpData": {"jobList": [{"encryptJobId": "SYN1", "jobName": "t", "bossOnline": True}]}})
    assert jobs[0]["boss_active_status"] == "在线"
