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

    # ---- Phase 2 dashboard (DASH-01 / DASH-02) ----
    "dashboard_h1": "Trang chính",
    "card_services_heading": "Trạng thái dịch vụ",
    "table_col_service": "Dịch vụ",
    "table_col_status": "Trạng thái",
    "table_col_action": "Thao tác",
    "badge_running": "● Đang chạy",
    "badge_stopped": "● Đã dừng",
    "badge_crashed": "● Crashed",
    "refresh_hint_template": "Tự động làm mới mỗi {seconds} giây",
    "services_empty_heading": "Chưa có dịch vụ nào để theo dõi",
    "services_empty_body": (
        "Cấu hình GAMEPATH trong /root/.quanlyserver.json rồi tải lại trang."
    ),
    # Plan 04 (M-7) will render this; key surfaced now for centralised i18n.
    "warning.ip_mac_drift": (
        "IP/MAC đã lưu không khớp interface hiện tại; vui lòng chọn lại và Lưu."
    ),

    # ---- Authenticated header bar ----
    "header_app_title": "Quản lý server",
    "header_logged_in": "Đã đăng nhập: {username}",  # Jinja interpolates
    "header_logout": "Đăng xuất",

    # ---- Phase 2 Plan 03: Start/Stop + tail-pane + toast (DASH-03/04/05) ----
    "btn_start_all": "▶ Start all",
    "btn_stop_all": "■ Stop all",
    "btn_start_row": "▶ Start",
    "btn_stop_row": "■ Stop",
    "tail_pane_heading": "Đầu ra",
    "tail_pane_empty": (
        "Chưa có lệnh nào được thực thi. Bấm \"Start all\" hoặc một nút Start để bắt đầu."
    ),
    "tail_pane_sublabel_running": "Đang chạy: {action} {service}",
    "tail_pane_sublabel_done": "Hoàn tất: {action} {service} — exit {code}",
    "tail_pane_sublabel_history": "Đang xem lịch sử: {action} {service} @ {ts}",
    "tail_pane_sse_lost": "Mất kết nối luồng log. Đang kết nối lại...",
    "tail_pane_job_pruned": "Log này đã bị xoá (chỉ giữ 20 job gần nhất).",
    "tail_pane_live_label": "— live —",
    "history_card_heading": "Lịch sử lệnh",
    "history_dropdown_label": "Chọn lệnh để xem lại",
    "history_default_option": "— Theo dõi lệnh mới nhất —",
    "history_empty": "Chưa có lịch sử lệnh.",
    "toast_lock_busy": "Đang có lệnh khác chạy, vui lòng đợi",
    "toast_job_sent": "Đã gửi lệnh: {action} {service}",
    "toast_job_failed": (
        "Lệnh kết thúc với lỗi (exit {code}). Xem chi tiết ở khung đầu ra."
    ),
    "error_500": "Lỗi máy chủ. Vui lòng tải lại trang hoặc kiểm tra /var/log/qlsv/.",
    "error_network": "Không thể liên hệ máy chủ. Đang thử lại...",
    "action_label_start_all": "Start all",
    "action_label_stop_all": "Stop all",
    "action_label_start": "Start",
    "action_label_stop": "Stop",
    "action_bar_running": "Đang chạy lệnh...",

    # ---- Phase 2 Plan 04: IP/MAC selector card (DASH-04 / D-15 / D-16 / M-7) ----
    "card_ip_mac_heading": "Cấu hình IP / MAC",
    "ip_mac_iface_label": "Giao diện mạng",
    "ip_mac_ip_label": "Địa chỉ IP",
    "ip_mac_mac_label": "Địa chỉ MAC",
    "ip_mac_save_btn": "Lưu cấu hình",
    "ip_mac_save_success": "Đã lưu cấu hình IP / MAC",
    "ip_mac_reconfig_banner": (
        "Cấu hình IP / MAC đã đổi. Stop rồi Start lại để áp dụng "
        "(gameconfigs/*.cfg sẽ được sync khi start)."
    ),
    "ip_mac_first_run_banner": (
        "Chưa cấu hình IP / MAC. Hãy chọn giao diện rồi bấm "
        "\"Lưu cấu hình\" trước khi khởi động dịch vụ."
    ),
    "ip_mac_no_ifaces_heading": "Không phát hiện giao diện mạng",
    "ip_mac_no_ifaces_body": (
        "Kiểm tra kết nối mạng của máy chủ rồi tải lại trang."
    ),
    "ip_mac_iface_not_found": "Giao diện mạng không tồn tại",

    # ---- Phase-2 gap closure: game directory picker (parity với 2.3.2/app.py:684) ----
    "card_game_dir_heading": "Thư mục server",
    "game_dir_input_label": "Đường dẫn thư mục game",
    "game_dir_save_btn": "Lưu thư mục",
    "game_dir_saved_message": "Đã lưu thư mục server.",
    "game_dir_suggestions_label": "Phát hiện trên máy chủ:",
    "game_dir_error_empty": "Vui lòng nhập đường dẫn.",
    "game_dir_error_relative": "Phải là đường dẫn tuyệt đối (bắt đầu bằng /).",
    "game_dir_error_missing": "Đường dẫn không tồn tại trên máy chủ.",
    "game_dir_error_not_dir": "Đường dẫn không phải là thư mục.",
    "game_dir_error_not_jx_tree": (
        "Thư mục không chứa cấu trúc JX1 hợp lệ — thiếu thư mục con "
        "\"gateway\" hoặc \"server1\"."
    ),

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
