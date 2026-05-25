"""Network interface enumeration helpers (ported from 2.3.2/app.py:77-128).

These helpers are used by Phase 2 to populate the *game-server IP* selector
in the dashboard (per `01-CONTEXT.md` D-11). They are explicitly NOT used
to decide what address the web app binds to — that comes from
``config.web.bind_addr``.

Filter rule (must match ``2.3.2/jx.sh:25``):
    interface == 'lo'  OR  'docker' in interface  → skipped
"""

from __future__ import annotations

import subprocess


def get_all_network_interfaces() -> list[dict]:
    """Return ``[{"interface", "ip", "mac"}, ...]`` for every non-lo/non-docker IPv4 iface.

    MAC is formatted ``"AA-BB-CC-DD-EE-FF"`` (upper, colons → dashes).
    Returns ``[]`` on any subprocess error (silent failure — parity with legacy).
    """
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        interfaces: list[dict] = []

        if result.returncode != 0:
            return interfaces

        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) < 4:
                continue

            interface = parts[1]
            # Skip loopback and docker interfaces (parity with jx.sh:25)
            if interface == "lo" or "docker" in interface:
                continue

            # Extract IP address (strip /24-style prefix)
            ip_with_prefix = parts[3]
            ip = ip_with_prefix.split("/")[0]

            # Read MAC from sysfs
            mac_result = subprocess.run(
                ["cat", f"/sys/class/net/{interface}/address"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            mac = (
                mac_result.stdout.strip().upper().replace(":", "-")
                if mac_result.returncode == 0
                else ""
            )

            interfaces.append({"interface": interface, "ip": ip, "mac": mac})

        return interfaces
    except Exception:
        # Silent failure — matches legacy 2.3.2/app.py:110-112 behavior
        # (the legacy code printed; we drop the print since the web layer
        # has no console to write to and no logger configured in Phase 1).
        return []


def get_lan_ip() -> str | None:
    """First non-lo, non-docker IPv4 address — or ``None`` if none available."""
    interfaces = get_all_network_interfaces()
    if not interfaces:
        return None
    return interfaces[0]["ip"]
