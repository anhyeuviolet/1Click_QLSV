# Running the qlsv web admin

Phase 1 ships a manual launch path for development. A `systemd` unit with
boot-time auto-start lands in Phase 4 — for now you start the app yourself.

---

## Quick start

```bash
# 1. Install the package (editable mode is fine on the server)
sudo pip install -e .

# 2. Configure /root/.quanlyserver.json — see docs/CONFIG.md
#    (set admin.username, admin.password, session.secret_key)

# 3. Launch the web admin
sudo bash scripts/run-web.sh
#    (equivalent to: sudo python -m qlsv)
```

Default URL: **http://<server-ip>:8080**

The app refuses to start with explicit Vietnamese error messages if the
required config is missing:

- `Chưa cấu hình admin (admin.username / admin.password). Sửa /root/.quanlyserver.json rồi thử lại.`
- `Thiếu session.secret_key. Xem docs/CONFIG.md để sinh khóa.`

Both messages link back to `docs/CONFIG.md`.

---

## LAN-only firewall guidance (OPS-03)

The web admin **binds to `0.0.0.0`** so any LAN host can reach it. The bind
address is *not* the access control — the firewall is. The app refuses to
serve HTTPS in Phase 1 (out of scope); if you must expose the box to the
internet, put it behind a reverse proxy that terminates TLS. Otherwise,
restrict port 8080 to your LAN subnet:

### iptables

```bash
# Allow LAN (adjust 192.168.0.0/16 to your subnet)
sudo iptables -A INPUT -p tcp --dport 8080 -s 192.168.0.0/16 -j ACCEPT
# Drop everything else trying to reach 8080
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

### ufw (Ubuntu-style)

```bash
sudo ufw allow from 192.168.0.0/16 to any port 8080 proto tcp
sudo ufw deny 8080
sudo ufw enable
```

---

## Troubleshooting

- **App refuses to start: `Chưa cấu hình admin ...`** — open
  `/root/.quanlyserver.json`, set `admin.username` and `admin.password` to
  real values (not `REPLACE_ME`). See `docs/CONFIG.md` § `admin`.
- **App refuses to start: `Thiếu session.secret_key ...`** — generate one
  with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and
  paste into `session.secret_key`. See `docs/CONFIG.md` § Generate.
- **Port already in use** — another process owns 8080. Either stop it or
  change `web.port` in the config file and restart.
- **Cannot reach the UI from another laptop** — check (a) the firewall
  rules above, (b) `web.bind_addr` is `0.0.0.0` (not `127.0.0.1`), and
  (c) the server's LAN IP matches what you typed in the browser.
- **Diacritics render as `??` or boxes** — confirm the JSON config file is
  saved as UTF-8 (no BOM). Bash output (jx.sh) is intentionally
  no-diacritics; only the web UI shows full Vietnamese.

---

## What changes in Phase 4

Phase 4 replaces the manual `python -m qlsv` launch with a `systemd` unit
that starts on boot, restarts on crash, and writes logs to the system
journal. For Phase 1 you launch it yourself; if the process dies you
restart it yourself.

---

## Log của game services (Phase 2)

Kể từ Phase 2, `scripts/jx.sh` không còn mở popup `xfce4-terminal` cho từng
tiến trình game. Thay vào đó, mỗi binary được khởi động qua `nohup` và
stdout/stderr được append vào file log riêng dưới `/var/log/qlsv/`.

### Vị trí log

**Per-service log** (do `scripts/jx.sh` ghi trực tiếp khi gọi
`bash scripts/jx.sh start <svc>`):

| Service     | File log                          |
|-------------|-----------------------------------|
| `goddess`   | `/var/log/qlsv/goddess.log`       |
| `bishop`    | `/var/log/qlsv/bishop.log`        |
| `s3relay`   | `/var/log/qlsv/s3relay.log`       |
| `jx_linux`  | `/var/log/qlsv/jx_linux.log`      |

**Per-job log** (web app sẽ tạo ở Plan 03 khi spawn jx.sh từ UI — note
trước để admin biết nơi tìm):

```
/var/log/qlsv/jobs/<job_id>.log
```

Mỗi lần click nút Start/Stop trên dashboard sẽ tạo một file mới với
`job_id` ngẫu nhiên; tail-pane trong UI đọc chính file này.

### Tail log để debug từ SSH

```bash
# Theo dõi log của bishop trong real-time
tail -f /var/log/qlsv/bishop.log

# Theo dõi nhiều service một lúc
tail -f /var/log/qlsv/*.log

# Xem 200 dòng cuối của goddess
tail -n 200 /var/log/qlsv/goddess.log
```

### Notes

- `scripts/jx.sh` **tự `mkdir -p /var/log/qlsv`** mỗi lần chạy lệnh start —
  admin không cần tạo thư mục trước.
- File log mặc định kế thừa umask của root (thường `0644`); chỉ root đọc
  được toàn bộ. Phase 3 sẽ điều chỉnh khi web app khởi tạo state dirs.
- **Log không tự rotate ở Phase 2.** Game binary có thể chạy tuần liền và
  file log sẽ phình lớn. Cơ chế logrotate sẽ thêm ở Phase 4 (deferred).
  Trong thời gian chờ, admin có thể truncate thủ công khi cần:

  ```bash
  truncate -s 0 /var/log/qlsv/bishop.log
  ```

  Lệnh này không làm gián đoạn tiến trình đang ghi (file descriptor giữ
  nguyên, nội dung bị xoá về 0 byte).
