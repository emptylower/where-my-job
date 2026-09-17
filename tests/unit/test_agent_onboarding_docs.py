# tests/unit/test_agent_onboarding_docs.py
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

def _read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")

def test_readme_starter_prompt_is_short_and_points_to_skill_scenarios():
    t = _read("README.md")
    assert "## 用 agent 开始（推荐）" in t
    assert t.index("## 用 agent 开始（推荐）") < t.index("## 安装")
    section = t.split("## 用 agent 开始（推荐）", 1)[1].split("\n## ", 1)[0]
    prompt = section.split("```text\n", 1)[1].split("\n```", 1)[0]
    assert "SKILL.md" in prompt and "场景：安装与自检" in prompt and "场景：首次使用" in prompt
    assert "不要让我自己去终端执行命令" in prompt and "demo" not in prompt
    assert len(prompt) < 300
    assert "where-my-job login start" in t and "where-my-job login status --wait 30" in t

def test_skill_first_use_logs_in_before_building_profile_and_demo_is_optional():
    t = _read("SKILL.md")
    first = t.split("### 场景：首次使用", 1)[1].split("\n### 场景：", 1)[0]
    assert first.index("扫码登录") < first.index("interview.md") < first.index("where-my-job scan --strategy F --dry-run")
    assert "data.online_adapter_default" in first and "合成 demo 只在" in first

def test_skill_login_puts_the_browser_window_first_and_makes_the_terminal_check_optional():
    """扫码面默认是专用 Chrome 窗口：GUI / TUI 前端没有"展开命令输出"这回事，
    终端字符画只能是备用。终端显示自检因此不能再当登录的前置步骤。"""
    t = _read("SKILL.md")
    login = t.split("#### 扫码登录", 1)[1].split("\n####", 1)[0]
    for s in ("`where-my-job login test-qr`", "`where-my-job login start`", "`where-my-job login status --wait 30`",
              "`where-my-job login cancel`", "ctrl+o", "qr_terminal_background", "--light-terminal", "30 秒",
              "读图工具", "init --browser", "--show-qr"):
        assert s in login, s
    assert "专用 Chrome 窗口" in login and "备用" in login
    assert "`surface`" in login and "`window_raised`" in login          # 给 agent 的机器可读依据
    assert login.index("`where-my-job login start`") < login.index("test-qr")   # 自检降级为可选，排在登录之后
    assert "不是登录的前置条件" in login
    assert "不要抄" in login and "data.login.qr_png" not in login

def test_skill_scan_scope_forbids_shrinking_the_user_request():
    """"只看第一页"曾经写在首次使用里，示例也只有单页样板——偷懒是写在文件里的。
    现在的规则是：按用户要的范围铺满；超额度只问一次；确认后立即执行，不再推辞。"""
    t = _read("SKILL.md")
    scope = t.split("#### 采集范围", 1)[1].split("\n### ", 1)[0]
    for s in ("不得自行缩小", "coverage.fits_budget", "planned_actions", "remaining_24h", "tasks_today",
              "tasks_deferred", "--partial", "只问一次", "不再劝阻", "BUDGET_EXHAUSTED"):
        assert s in scope, s
    assert "城市不是白名单" in scope and "101270100" in scope and "city_codes" in scope
    assert "只看第一页" not in t and "第一页采集" not in t

def test_skill_tells_agent_how_to_talk_to_users():
    t = _read("SKILL.md")
    talk = t.split("### 对用户怎么说", 1)[1].split("\n## ", 1)[0]
    assert "| 不要这样说 | 这样说 |" in talk and "退出码" in talk and "错误码" in talk
    assert "AskUserQuestion" in t
    for s in ("ln -s ~/where-my-job ~/.claude/skills/where-my-job", "~/.kimi-code/skills/where-my-job"):
        assert s in t, s

def test_skill_explains_document_diagnostics_on_capture_failure():
    t = _read("SKILL.md")
    assert "data.documents" in t and "站外子文档" in t and "平台自己的中间跳会被放行" in t

def test_checklist_explains_the_three_document_outcomes():
    c = _read("tests", "manual", "ONLINE_CHECKLIST.md")
    section = c.split("## 3. Document 拦截（R2 必查）", 1)[1].split("\n## ", 1)[0]
    for s in ("/web/passport/zp/security.html", "落回期望页", "退出 3", "refused_subframes"):
        assert s in section, s

def test_docs_do_not_claim_a_thirty_second_expiry_and_explain_the_rotation():
    skill, privacy = _read("SKILL.md"), _read("skill", "references", "privacy-boundary.md")
    for text in (skill, privacy):
        assert "二维码大约 30 秒失效" not in text
    assert "每 30 秒换一张" in skill and "expiry_marker" in skill
    assert "自己换一张二维码" in privacy

def test_demo_block_can_run_without_a_global_install():
    skill = _read("SKILL.md")
    demo = skill.split("#### 合成 demo 命令", 1)[1].split("```bash\n", 1)[1].split("\n```", 1)[0]
    assert 'WMJ="where-my-job"' in demo and "uv run --project" in demo
    assert "\nwhere-my-job " not in demo          # demo 内不再出现裸命令
    assert "uv run --project ~/where-my-job where-my-job" in skill    # 安装表格并列了开发态

def test_references_match_actual_behaviour():
    scoring = _read("skill", "references", "scoring-schema.md")
    events = _read("skill", "references", "event-schema.md")
    interview = _read("skill", "references", "interview.md")
    assert "不能仅提供白名单而不限制资格" not in scoring and "experience-allowlist" in scoring
    assert "## 内置流 `applications` 的 payload 字段" in events and "`round` **字符串**" in events
    assert "只是习惯命名" in interview

def test_interview_starts_from_resume_or_choice_questions():
    t = _read("skill", "references", "interview.md")
    assert "## 第一步：问有没有简历" in t and "选项不超过 4 个" in t
    assert "联系方式" in t and "经验不限" in t and "10年以上" in t

def test_privacy_boundary_covers_qr_drawing_resume_reading_and_redacted_urls():
    t = _read("skill", "references", "privacy-boundary.md")
    login = t.split("## 扫码登录", 1)[1].split("\n## ", 1)[0]
    for s in ("state/login-qr.png", "0600", "stderr", "模型提供商", "最多刷新 6 次", "init --browser"):
        assert s in login, s
    assert "明确交给你的文件" in t
    assert "只记地址的主机、路径与查询参数名" in t and "不记参数值" in t

def test_checklist_records_drawing_and_document_diagnostics():
    c = _read("tests", "manual", "ONLINE_CHECKLIST.md")
    a = _read("docs", "acceptance", "TEMPLATE-beta-acceptance.md")
    assert "## 2b. 扫码登录（agent 驱动）" in c and "login status --wait 30" in c and "超过 11 次受控动作" in c
    assert "字符画" in c and "--light-terminal" in c and "ctrl+o" in c
    assert "refused_subframes" in c and "data.documents" in c
    assert "开场 prompt" in a and "where-my-job login start" in a and "展示二维码图片" not in a
