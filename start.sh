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

# ---- Bootstrap lan dau: tao config tu template ------------------------------

if [ ! -f "$CONFIG" ]; then
  cp "$TEMPLATE" "$CONFIG"
  chmod 0600 "$CONFIG"
  SECRET=$("$VENV/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")
  # Use a sed delimiter that cannot appear in token_urlsafe output (only [A-Za-z0-9_-]).
  sed -i "s|\"secret_key\": \"REPLACE_ME\"|\"secret_key\": \"$SECRET\"|" "$CONFIG"

  echo ""
  echo "==> Da tao $CONFIG voi secret_key ngau nhien."
  echo "    Sua admin.username va admin.password thanh gia tri that, roi chay lai:"
  echo ""
  echo "    sudo nano $CONFIG"
  echo "    sudo bash start.sh"
  exit 0
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
