"""Vietnamese user-facing string table for the qlsv web admin.

Single source of truth for all user-facing copy rendered by the Phase 1
Jinja2 templates (login + dashboard placeholder). Bash output remains
no-diacritics (per CONVENTIONS) so this module deliberately covers only
the Python/HTML surface.

Merged from the two legacy Tkinter dicts:
- 2.3.2/app.py:36-52  (main dashboard)
- 2.3.2/users.py:~101 (account manager — duplicate, subset of the above)

Conflict resolution: on overlap, the 2.3.2/app.py value wins. There were no
value conflicts in practice — users.py is a strict subset (missing
``button_patchServer`` and ``button_log``).

The obsolete version-string key was dropped in v3; consumers should read
``qlsv.__version__`` instead.
"""

# UI-SPEC Copywriting Contract keys (Phase 1 login + dashboard) live alongside
# the merged legacy keys. Diacritics are stored as literal UTF-8 — do not
# escape with ``\u...`` sequences.
TRANSLATION: dict[str, str] = {
    # ---- Page titles (UI-SPEC § Copywriting Contract) ----
    "tab_title_login": "Quản lý server — Đăng nhập",
    "tab_title_dashboard": "Quản lý server — Trang chính",

    # ---- Login form ----
    "login_title": "Quản lý server",
    "login_subheading": "Đăng nhập để tiếp tục",
    "login_username_label": "Tên đăng nhập",
    "login_password_label": "Mật khẩu",
    "login_submit": "Đăng nhập",
    "login_error_invalid": "Tên đăng nhập hoặc mật khẩu không đúng",

    # ---- Dashboard placeholder ----
    "dashboard_placeholder_heading": "Trang chính",
    "dashboard_placeholder_body": (
        "Bảng điều khiển sẽ được bổ sung ở các giai đoạn tiếp theo. "
        "Hiện tại bạn đã đăng nhập thành công."
    ),

    # ---- Authenticated header bar ----
    "header_app_title": "Quản lý server",
    "header_logged_in": "Đã đăng nhập: {username}",  # Jinja interpolates
    "header_logout": "Đăng xuất",

    # ---- Legacy keys merged from 2.3.2/app.py:36-52 ----
    # (package version available via qlsv.__version__; legacy version key dropped)
    "app_title": "Quản lý server",
    "status_off": "đã tắt",
    "status_on": "đang chạy",
    "button_on": "Mở",
    "button_off": "Tắt",
    "button_backup": "Backup",
    "button_log": "log",
    "button_start_all": "Mở tất cả",
    "button_stop_all": "Tắt tất cả",
    "button_users": "Tài khoản",
    "button_changeServer": "Đổi server",
    "button_patchServer": "Up",
    "autostart": "boot",
}
