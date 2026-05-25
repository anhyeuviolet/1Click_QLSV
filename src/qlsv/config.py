"""Config loader for qlsv.

Reads `/root/.quanlyserver.json`, auto-migrates legacy flat schema to nested v3 form,
validates required keys with Vietnamese fail-fast errors, and writes atomically with
chmod 0600 on POSIX (D-03, D-07, D-12, D-13).

Public API (contract — Plan 02 / Plan 03 consume):
  CONFIGFILE: str
  class ConfigError(Exception)
  load_config(path=CONFIGFILE) -> dict
  save_config(data, path=CONFIGFILE) -> None
  migrate_if_needed(path=CONFIGFILE) -> bool
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
from typing import Any

from qlsv._atomic import write_json

CONFIGFILE: str = "/root/.quanlyserver.json"
BACKUP_SUFFIX: str = ".pre-v3.bak"

# Dotted-path keys that MUST be present and non-empty at startup (D-03, D-07).
REQUIRED_KEYS: tuple[str, ...] = (
    "admin.username",
    "admin.password",
    "session.secret_key",
)

# Top-level keys belonging to the legacy flat schema (D-13).
LEGACY_GAME_KEYS: tuple[str, ...] = ("directory", "server_ip", "server_mac")

# Default values applied to `web` section if absent. Admin shouldn't need to set
# these explicitly (D-08, D-09, D-10).
WEB_DEFAULTS: dict[str, Any] = {
    "bind_addr": "0.0.0.0",
    "port": 8080,
    "idle_timeout_seconds": 2592000,
    "cookie_secure": False,
}

# Default values applied to `dashboard` section if absent (Plan 02 D-09).
DASHBOARD_DEFAULTS: dict[str, Any] = {
    "poll_interval_seconds": 5,
}

# Bind addresses that would lock admins out of the LAN (WEB-02 / M-2).
# Both IPv4 loopback (entire 127.0.0.0/8) and IPv6 loopback variants are rejected.
LOOPBACK_DENY: frozenset[str] = frozenset({
    "127.0.0.1",
    "localhost",
    "::1",
    "0:0:0:0:0:0:0:1",
})


class ConfigError(Exception):
    """Raised on missing / invalid / unreadable config.

    Always carries a Vietnamese, admin-readable message.
    """


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _dotted_get(d: dict, dotted: str) -> Any:
    """Walk a dotted path; return None if any step missing."""
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_config(data: dict, path: str = CONFIGFILE) -> None:
    """Atomically write `data` as JSON to `path`, then chmod 0600 on POSIX.

    Thin wrapper around ``qlsv._atomic.write_json`` (Phase 2 H-6 — shared
    helper). Behaviour-identical to the inline implementation Phase 1
    shipped: tmp+rename, 0600 from creation, Windows fallback.
    """
    write_json(path, data, mode=0o600)


def migrate_if_needed(path: str = CONFIGFILE) -> bool:
    """If `path` holds a legacy flat schema, reshape it to nested v3 form.

    Behaviour (D-13):
      - Detects any of LEGACY_GAME_KEYS at top level.
      - If detected: copies original bytes to `path + BACKUP_SUFFIX`, builds the
        new nested dict (legacy keys land under `game`; everything else preserved
        verbatim), writes back via `save_config`.
      - Idempotent: returns False if file is already nested.

    Returns True iff migration was performed. Errors (missing file, bad JSON)
    are swallowed — `load_config` is the canonical error path.
    """
    if not os.path.exists(path):
        return False
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    has_legacy = any(k in data for k in LEGACY_GAME_KEYS)
    if not has_legacy:
        return False

    # Back up the original first (T-01-04). Refuse to overwrite an existing
    # backup so the original v2.x recovery copy is preserved across re-runs.
    backup = path + BACKUP_SUFFIX
    if not os.path.exists(backup):
        shutil.copy2(path, backup)

    new: dict[str, Any] = {}
    game_section: dict[str, Any] = dict(data.get("game", {})) if isinstance(data.get("game"), dict) else {}
    for k in LEGACY_GAME_KEYS:
        if k in data:
            game_section.setdefault(k, data[k])
        else:
            game_section.setdefault(k, "")
    # Copy everything except legacy keys / existing `game`
    for k, v in data.items():
        if k in LEGACY_GAME_KEYS or k == "game":
            continue
        new[k] = v
    new["game"] = game_section

    save_config(new, path)
    return True


def load_config(path: str = CONFIGFILE) -> dict:
    """Load and validate config at `path`. Raises ConfigError on any failure.

    - Missing file → Vietnamese "Không tìm thấy" message.
    - Bad JSON → Vietnamese "Không đọc được" message.
    - Triggers `migrate_if_needed` after a successful initial read.
    - Validates REQUIRED_KEYS (non-empty); raises "Chưa cấu hình admin..." on miss.
    - Applies WEB_DEFAULTS for absent `web` keys.
    """
    if not os.path.exists(path):
        raise ConfigError(f"Không tìm thấy tệp cấu hình: {path}")

    try:
        data = _read_json(path)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Không đọc được tệp cấu hình {path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"Không đọc được tệp cấu hình {path}: {e}") from e

    # Migrate flat → nested if needed, then re-read.
    if migrate_if_needed(path):
        try:
            data = _read_json(path)
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError(f"Không đọc được tệp cấu hình {path} sau khi nâng cấp: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"Tệp cấu hình {path} không hợp lệ (phải là object JSON)")

    # Validate required keys (present AND non-empty).
    missing: list[str] = []
    for dotted in REQUIRED_KEYS:
        v = _dotted_get(data, dotted)
        if v is None or (isinstance(v, str) and v.strip() == ""):
            missing.append(dotted)
    if missing:
        raise ConfigError(
            "Chưa cấu hình admin trong " + path + " (" + ", ".join(missing) + ")"
        )

    # Apply web defaults if absent.
    web = data.setdefault("web", {})
    if isinstance(web, dict):
        for k, default in WEB_DEFAULTS.items():
            web.setdefault(k, default)

        # WEB-02 / M-2: reject loopback bind_addr (IPv4 + IPv6 variants).
        # Fail-fast in Vietnamese; do NOT silently bind to a LAN-unreachable
        # address.
        raw = web.get("bind_addr", "")
        bind_addr = str(raw).strip().lower()
        # Strip IPv6 bracket form `[...]`.
        if bind_addr.startswith("[") and bind_addr.endswith("]"):
            bind_addr_check = bind_addr[1:-1]
        else:
            bind_addr_check = bind_addr

        is_loopback = False
        if bind_addr_check in LOOPBACK_DENY:
            is_loopback = True
        elif bind_addr_check.startswith("127."):
            # Entire IPv4 loopback /8 — covers 127.0.0.5 etc.
            is_loopback = True
        else:
            # Defensive parse for canonical/non-canonical IPv6 loopback forms.
            try:
                is_loopback = ipaddress.ip_address(bind_addr_check).is_loopback
            except ValueError:
                # Not an IP literal — could be a hostname like "myserver.local".
                # We do not resolve hostnames; admin is on the hook for those.
                is_loopback = False

        if is_loopback:
            raise ConfigError(
                "web.bind_addr không được trỏ loopback (WEB-02). "
                "Dùng 0.0.0.0 hoặc địa chỉ LAN cụ thể."
            )

    # Apply dashboard defaults if absent (Plan 02 — poll_interval_seconds).
    dash = data.setdefault("dashboard", {})
    if isinstance(dash, dict):
        for k, default in DASHBOARD_DEFAULTS.items():
            dash.setdefault(k, default)

    return data
