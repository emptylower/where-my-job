import re
from where_my_job.public_messages import PUBLIC_FAILURE_MESSAGES, public_message

def test_fixed_messages_have_no_urls_digits_or_placeholders():
    for code, text in PUBLIC_FAILURE_MESSAGES.items():
        assert re.fullmatch(r"[A-Z_]+", code)
        assert "http" not in text and "{" not in text and not re.search(r"\d{3,}", text)

def test_unknown_code_falls_back_to_internal():
    assert public_message("NOPE") == PUBLIC_FAILURE_MESSAGES["INTERNAL"]

def test_login_codes_have_fixed_messages():
    assert "扫码登录" in public_message("LOGIN_NOT_STARTED")
    assert "超时" in public_message("LOGIN_TIMEOUT")
