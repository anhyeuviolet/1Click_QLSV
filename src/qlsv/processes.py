"""Liveness probes cho 6 service game (D-09, D-10, D-13).

Public API (PATTERNS.md §processes.py — Plan 03 và Phase 4 monitor sẽ tái dùng):
  ALLOWED_SERVICES: frozenset[str]
  SERVICE_PGREP_PATTERNS: dict[str, str]
  SERVICE_DISPLAY_LABELS: dict[str, str]
  is_alive(service) -> bool
  probe_all() -> dict[str, bool]
  compute_status(service, expected_running, process_alive) -> str

Mỗi poll cycle gọi ``probe_all`` mới — KHÔNG cache (D-09: overhead 1.2 calls/s
chấp nhận được trên host single-admin; Phase 4 có thể tối ưu sang ``ps -eo comm``).

Service whitelist (D-13) chặn tham số xấu từ URL Plan 03 trước khi pattern đi vào
``pgrep -f`` — xem T-02-08.
"""
from __future__ import annotations

import subprocess

__all__ = [
    "ALLOWED_SERVICES",
    "SERVICE_PGREP_PATTERNS",
    "SERVICE_DISPLAY_LABELS",
    "is_alive",
    "probe_all",
    "compute_status",
]


# Whitelist enum (D-13 / T-02-08). Iteration order of SERVICE_PGREP_PATTERNS
# below is the canonical render order for the dashboard table.
ALLOWED_SERVICES: frozenset[str] = frozenset(
    {"bishop", "goddess", "s3relay", "jx_linux", "PaySys", "RelayServer"}
)

# pgrep -f pattern per service. Linux binaries end with _y; Wine processes carry
# the .exe suffix verbatim (per 2.3.2/app.py:639-647, 2.3.2/jx.sh:103,123,141,158).
#
# Iteration order = UI render order = start-all sequence:
#   PaySys + RelayServer first (Wine auth/relay), then goddess + bishop + s3relay
#   (gateway tier), finally jx_linux (game server, depends on the rest).
SERVICE_PGREP_PATTERNS: dict[str, str] = {
    "PaySys": "Sword3PaySys.exe",
    "RelayServer": "S3RelayServer.exe",
    "goddess": "goddess_y",
    "bishop": "bishop_y",
    "s3relay": "s3relay_y",
    "jx_linux": "jx_linux_y",
}

# UI labels — short Wine names that match the start/stop button vocabulary.
SERVICE_DISPLAY_LABELS: dict[str, str] = {
    "PaySys": "PaySys",
    "RelayServer": "RelayServer",
    "goddess": "goddess",
    "bishop": "bishop",
    "s3relay": "s3relay",
    "jx_linux": "jx_linux",
}


def is_alive(service: str) -> bool:
    """Return True iff ``pgrep -f <pattern>`` reports the service is running.

    Raises ``ValueError`` (with a Vietnamese message) if ``service`` is not in
    ``ALLOWED_SERVICES`` — defends Plan 03 endpoints that take a service name
    from the URL (T-02-08). Any OS-level error (pgrep missing, subprocess
    raises) is swallowed and reported as False.
    """
    if service not in ALLOWED_SERVICES:
        raise ValueError("Service không hợp lệ")
    pattern = SERVICE_PGREP_PATTERNS[service]
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def probe_all() -> dict[str, bool]:
    """Probe every service in ``SERVICE_PGREP_PATTERNS`` and return ``{svc: alive}``.

    Order matches ``SERVICE_PGREP_PATTERNS`` insertion order (= render order
    in the dashboard table). One ``pgrep`` call per service, no caching.
    """
    return {svc: is_alive(svc) for svc in SERVICE_PGREP_PATTERNS}


def compute_status(service: str, expected_running: bool, process_alive: bool) -> str:
    """Resolve the badge state per truth table D-10.

    | expected_running | process_alive | status   |
    |------------------|---------------|----------|
    | *                | True          | running  |
    | True             | False         | crashed  |
    | False            | False         | stopped  |

    The ``service`` argument is accepted for forward-compat (logging /
    metrics) but does not affect the result — the status is a pure function
    of the two booleans.
    """
    if process_alive:
        return "running"
    if expected_running:
        return "crashed"
    return "stopped"
