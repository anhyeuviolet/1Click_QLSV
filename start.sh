#!/usr/bin/env bash
# 1Click launcher cho qlsv-web (Phase 2).
#
# Lan dau: tu cai venv + deps + tao config tu template (chi mat ~30s).
# Lan sau: chi launch — vai giay la len.
#
# Goi:  sudo bash start.sh
#
# Phase 4 se thay bang systemd unit chay luc boot, khi do admin
# khong can go lenh gi ca.

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
APPPATH="$(cd -P "$(dirname "$SOURCE")" && pwd)"
cd "$APPPATH"

VENV="$APPPATH/.venv"
CONFIG="/root/.quanlyserver.json"
TEMPLATE="$APPPATH/configs/quanlyserver.example.json"

if [ "$(id -u)" -ne 0 ]; then
  echo "Loi: can chay bang root (sudo bash start.sh) — app ghi /root/.quanlyserver.json va /var/log/qlsv/." >&2
  exit 1
fi

# ---- Bootstrap lan dau: cai venv + deps -------------------------------------

if [ ! -x "$VENV/bin/python" ]; then
  echo "Lan dau khoi dong — dang cai dat moi truong (~30s, can Internet)..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y python3-venv python3-pip >/dev/null
  fi
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -e .
  echo "Da cai xong moi truong vao $VENV"
fi

# ---- Bootstrap lan dau: tao config tu template + hoi admin ------------------

if [ ! -f "$CONFIG" ]; then
  echo ""
  echo "Chua co $CONFIG. Tao moi tu template."
  echo "Nhap thong tin admin dung de login web (http://<server-ip>:8080):"
  echo ""

  ADMIN_USER=""
  while [ -z "$ADMIN_USER" ]; do
    read -r -p "  Username: " ADMIN_USER </dev/tty
    if [ -z "$ADMIN_USER" ]; then
      echo "  Username khong duoc de trong."
    fi
  done

  ADMIN_PASS=""
  while [ -z "$ADMIN_PASS" ]; do
    read -r -s -p "  Password: " ADMIN_PASS </dev/tty
    echo
    if [ -z "$ADMIN_PASS" ]; then
      echo "  Password khong duoc de trong."
      continue
    fi
    read -r -s -p "  Nhap lai password: " ADMIN_PASS2 </dev/tty
    echo
    if [ "$ADMIN_PASS" != "$ADMIN_PASS2" ]; then
      echo "  Hai lan nhap password khac nhau, thu lai."
      ADMIN_PASS=""
    fi
  done

  # Render config via Python — handles JSON escaping correctly (quotes, backslashes,
  # unicode) and generates secret_key in the same process. Safer than sed.
  ADMIN_USER="$ADMIN_USER" ADMIN_PASS="$ADMIN_PASS" \
  TEMPLATE_PATH="$TEMPLATE" CONFIG_PATH="$CONFIG" \
    "$VENV/bin/python" - <<'PY'
import json, os, secrets, sys
template = os.environ["TEMPLATE_PATH"]
target = os.environ["CONFIG_PATH"]
with open(template, "r", encoding="utf-8") as f:
    cfg = json.load(f)
cfg.setdefault("admin", {})["username"] = os.environ["ADMIN_USER"]
cfg["admin"]["password"] = os.environ["ADMIN_PASS"]
cfg.setdefault("session", {})["secret_key"] = secrets.token_urlsafe(48)
# Open with 0o600 from creation so the password is never world-readable, even briefly.
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY

  unset ADMIN_PASS ADMIN_PASS2
  echo ""
  echo "==> Da tao $CONFIG (mode 0600, secret_key sinh ngau nhien)."
fi

# ---- Single-instance check --------------------------------------------------

if pgrep -f "qlsv.__main__\|python.*-m qlsv" >/dev/null 2>&1; then
  echo "qlsv-web da chay roi (pgrep tim thay tien trinh). Khong khoi dong lan thu hai."
  exit 0
fi

# ---- Launch -----------------------------------------------------------------
# D-12: uvicorn --workers 1 enforced by `python -m qlsv` entrypoint.

echo "Khoi dong qlsv-web — mo http://<server-ip>:8080 tren browser."
exec "$VENV/bin/python" -m qlsv
