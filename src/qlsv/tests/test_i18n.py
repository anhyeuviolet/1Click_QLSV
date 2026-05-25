"""Tests for qlsv.i18n — merged TRANSLATION dict.

Verifies that the dict produced by merging the two legacy ``TRANSLATION``
mappings in ``2.3.2/app.py`` and ``2.3.2/users.py`` and the Phase 1 UI-SPEC
copywriting contract carries the required keys with diacritics intact.
"""

from qlsv.i18n import TRANSLATION


def test_translation_is_dict_with_string_values():
    assert isinstance(TRANSLATION, dict)
    assert len(TRANSLATION) > 0
    for k, v in TRANSLATION.items():
        assert isinstance(k, str), f"key {k!r} is not a string"
        assert isinstance(v, str), f"value for {k!r} is not a string: {v!r}"


def test_required_login_keys_present():
    expected = {
        "tab_title_login": "Quản lý server — Đăng nhập",
        "tab_title_dashboard": "Quản lý server — Trang chính",
        "login_title": "Quản lý server",
        "login_subheading": "Đăng nhập để tiếp tục",
        "login_username_label": "Tên đăng nhập",
        "login_password_label": "Mật khẩu",
        "login_submit": "Đăng nhập",
        "login_error_invalid": "Tên đăng nhập hoặc mật khẩu không đúng",
        "dashboard_placeholder_heading": "Trang chính",
        "dashboard_placeholder_body": (
            "Bảng điều khiển sẽ được bổ sung ở các giai đoạn tiếp theo. "
            "Hiện tại bạn đã đăng nhập thành công."
        ),
        "header_app_title": "Quản lý server",
        "header_logged_in": "Đã đăng nhập: {username}",
        "header_logout": "Đăng xuất",
    }
    for key, value in expected.items():
        assert key in TRANSLATION, f"missing key {key!r}"
        assert TRANSLATION[key] == value, (
            f"key {key!r} value mismatch: got {TRANSLATION[key]!r}, "
            f"expected {value!r}"
        )


def test_legacy_keys_preserved():
    expected = {
        "app_title": "Quản lý server",
        "status_off": "đã tắt",
        "status_on": "đang chạy",
        "button_on": "Mở",
        "button_off": "Tắt",
        "button_backup": "Backup",
        "button_start_all": "Mở tất cả",
        "button_stop_all": "Tắt tất cả",
        "button_users": "Tài khoản",
        "button_changeServer": "Đổi server",
        "button_patchServer": "Up",
        "autostart": "boot",
    }
    for key, value in expected.items():
        assert key in TRANSLATION, f"missing legacy key {key!r}"
        assert TRANSLATION[key] == value, (
            f"legacy key {key!r} value mismatch: got {TRANSLATION[key]!r}, "
            f"expected {value!r}"
        )


def test_no_app_version_legacy_key():
    assert "app_version" not in TRANSLATION, (
        "obsolete 'app_version' key must be removed — use qlsv.__version__"
    )


def test_diacritics_intact():
    # Byte-level equality with literal UTF-8 strings
    assert TRANSLATION["login_submit"] == "Đăng nhập"
    assert TRANSLATION["login_password_label"] == "Mật khẩu"
    assert TRANSLATION["login_title"] == "Quản lý server"
    # UTF-8 byte length sanity
    assert "Đăng nhập".encode("utf-8") == TRANSLATION["login_submit"].encode("utf-8")


def test_header_logged_in_has_format_placeholder():
    assert "{username}" in TRANSLATION["header_logged_in"]
