# 上游来源

- 项目：boss-zhipin-scraper（eatmoreduck），MIT License（同目录 LICENSE 逐字复制）
- commit：`eb5a8e646d4e4bfc024cf53f2a5b543ad8d75edc`
- 文件：`scripts/boss_cdp_raw.py`，整体 SHA256 `2d28e3a1915d20fff031b8b79eeffff9c0e815f40ee2d5ef217a3b2d73a6a91f`
- 复制方式：按上游行号顺序逐字截取顶层对象（含装饰器），函数体、字符串、注释均未修改
- 导入行：仅 `import re`、`from dataclasses import dataclass`、`from enum import Enum`、`from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl`

## 复制清单（32 项）

| 对象 | 上游行 | 该段 SHA256 | 用途 |
|---|---|---|---|
| `DEFAULT_CDP_PORT` | L72–L72 | `8fbe85ed0c44a483b121aac29b335611ea43b4bc9eadb64febdae532fee95e4e` | 默认端口 |
| `API_JOB_LIST_PATH` | L75–L75 | `164c7ae978b72e27223b0102564d42dfb38d6e69cebc2a3e75a90f0bf8cca98f` | 捕获路径 |
| `PROBE_CAPTURE_TIMEOUT` | L197–L197 | `74202c0fcc3e9e4599ebe579b93a222e343cf677dce6c9796d8bbc94c80810a8` | 捕获超时 |
| `LOGIN_RESTRICTED_CODES` | L198–L198 | `2f28f96fe35dfab450fa791c145af2527196b9ee70591153fe3b6f485ac46f98` | 响应分类 |
| `LOGIN_RESTRICTED_MESSAGE_KEYWORDS` | L201–L208 | `8e3a1c65566a389335543650c2665b394daa8ba05df2082f04d6710ef6afd81f` | 响应分类 |
| `SCALE_MAP` | L310–L313 | `77ff48d58cea97929d0e89b0f6e44c6d37f7ffeae8dfbf437ef0827da8c10321` | 码表 |
| `STAGE_MAP` | L315–L318 | `fd3726771fae0b0dd0589e916abceadb9afa91874f3fe533064e16c44d450eae` | 码表 |
| `SALARY_MAP` | L320–L323 | `40c1ca5b51d6e9160b61a8adda6426675794324e07892ba49ee5a88690900edb` | 码表 |
| `EXPERIENCE_MAP` | L325–L329 | `8151464f715633e3f90364bb95302662e9c1e49e96d62defe3a7f18c6048b457` | 码表 |
| `DEGREE_MAP` | L331–L334 | `a58dc86986bc803033498564dfdc4e1445433704d41c166f7692474dec1449b0` | 码表 |
| `INDUSTRY_MAP` | L336–L340 | `cbdd5218e2228771f7e0b4d6107c142623ad1bea5bee6305840833bc83877ffd` | 码表 |
| `map_api_job` | L599–L641 | `ce69016082f62ab1d96b0f53e932fa7fe60b7c3c90a30a3b7d5aeed06078f0fb` | 列表条目映射 |
| `map_api_jobs` | L644–L651 | `9683beac37118912146d23d01c1ae9d37d7460ee1e6e541872d92ce8a3b743e9` | 列表条目映射 |
| `DETAIL_LOGIN_MARKER` | L696–L696 | `1058c2dc086366e7a8ecd4b2b1ff34dd2a7e1f7b5d30b048ba3f8e459067b3b1` | 详情页解析 |
| `DETAIL_DESCRIPTION_MARKER` | L697–L697 | `9e6bff48b2df0e5b22a6385b4c6472113ba1ad99b1a0ab4b6672809bcab6dc98` | 详情页解析 |
| `DETAIL_COMPETITIVENESS_MARKER` | L698–L698 | `e37381d8ab37320f31fe9a5322845775ab80bd181c16cb9660e76dcda2d9a9eb` | 详情页解析 |
| `DETAIL_SAFETY_MARKER` | L699–L699 | `9551d08e9b3a7547a1ad73603290595a4b6639ad38ed6d9426ad025d818ca867` | 详情页解析 |
| `MIN_DETAIL_TEXT_LENGTH` | L700–L700 | `733d3ac640fa5462deebee0ebdd686a52de7e3a9f14fcb8d4ea932afe3401425` | 详情页解析 |
| `DetailExtractionError` | L703–L704 | `d5bbac9609948bd6ceeac7143c66134c8c457456f9f09ab1f4d5e38693600583` | 详情页解析 |
| `DetailLoginRequiredError` | L707–L708 | `e1b967407a4e4491ac1d913d7ec72b46de2e8c79146db324f180565f12e25e26` | 详情页解析 |
| `EXTRACT_DETAIL_JS` | L711–L750 | `27fe3cfd1aec7802a55b3d313d1c8f9379a14be20b54a862856250d88b04c4c1` | 详情页解析 |
| `_normalize_detail_whitespace` | L753–L757 | `9e2523c075a40cbc2c520c62202bfbf563e7f40a993eb87f70953bbbbea3281d` | 详情页解析 |
| `_looks_like_navigation_page` | L760–L767 | `9f6cfcd8baba691d0ba2e171f078085f24f03f6fdd0a78231c4927db4800d82c` | 详情页解析 |
| `_is_boss_activity_line` | L770–L772 | `160434cb9a9068bc88412169b91ae37d2bea60517db9b1583a47f2582e20b09c` | 详情页解析 |
| `map_list_boss_active_status` | L775–L790 | `97a7cf624596f546227954446df9f10258ff45f5588b2f762d22ec323d95ee15` | 列表条目映射 |
| `_recruiter_footer_info` | L801–L838 | `c661928ad863c55f5567279e1d7e77c0da9901bc27c8b065ca2e243703c5938e` | 详情页解析 |
| `extract_detail_fields` | L846–L890 | `731966b1debc78f3cede42b70b553ab6f9ffe45105147f05785d46c58bd381ea` | 详情页解析 |
| `extract_job_description` | L893–L895 | `34f47c5eec99601264eaff0b32f1d25ac2985fc12686423f3fd0973837c61d07` | 详情页解析 |
| `LoginProbeStatus` | L1027–L1034 | `9df071a88b5431f7f1809cd98a6f737454a6f6b48f02f61cb11cb32ed9ed474c` | 响应分类 |
| `LoginProbeResult` | L1037–L1044 | `f0fd5966ab8fd768fc9738ed14a573d0daf629b01fc58c4fc2b2b31006e3c0a2` | 响应分类 |
| `classify_login_probe_response` | L1047–L1112 | `a478b5a9219a2d5018fd1876c153392b5024ddc3a4315f0cc991b94259d5be43` | 响应分类 |
| `build_search_url` | L1442–L1447 | `a499a2f57480ac1c67147383df5b8953f64c54b5f79a443d5c5cdc1437562081` | 搜索 URL |

## 明确不复制

`CDPSession`、`NetworkJoblistCapture`、`create_page_session`、`BACKGROUND_VISIBILITY_SCRIPT`、`run_setup_chrome`（带 `--remote-allow-origins=*`）、分页循环、`scrape_details`、DOM fallback `EXTRACT_LIST_JS`、在线城市码表、`incr_request`、`main`。CDP 会话、日志与所有动作循环由 `where_my_job.adapter` 自行实现。

## 偏离

无。
