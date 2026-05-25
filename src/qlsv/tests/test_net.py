"""Tests for qlsv.net — network interface enumeration helpers.

Ports of the legacy ``getAllNetworkInterfaces`` / ``getLANIP`` from
``2.3.2/app.py:77-128``. All tests monkeypatch ``subprocess.run`` so they
are platform-independent and run on Windows during development.
"""

import subprocess

import pytest

from qlsv import net


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _make_run(ip_output: str, mac_map: dict[str, str]):
    """Build a fake ``subprocess.run`` that returns ip-addr output then per-iface MAC reads."""

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 and cmd[0] == "ip":
            return _FakeCompleted(stdout=ip_output, returncode=0)
        if isinstance(cmd, (list, tuple)) and cmd[0] == "cat":
            target = cmd[1]
            # /sys/class/net/<iface>/address
            iface = target.split("/")[-2]
            mac = mac_map.get(iface, "")
            if mac:
                return _FakeCompleted(stdout=mac + "\n", returncode=0)
            return _FakeCompleted(stdout="", returncode=1)
        return _FakeCompleted(stdout="", returncode=1)

    return fake_run


def test_get_all_network_interfaces_filters_lo(monkeypatch):
    ip_out = (
        "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
        "2: eth0    inet 192.168.1.10/24 scope global eth0\\       valid_lft forever preferred_lft forever\n"
        "3: docker0    inet 172.17.0.1/16 scope global docker0\\       valid_lft forever preferred_lft forever\n"
        "4: enp0s3    inet 10.0.0.5/24 scope global enp0s3\\       valid_lft forever preferred_lft forever\n"
    )
    mac_map = {
        "eth0": "aa:bb:cc:dd:ee:ff",
        "enp0s3": "11:22:33:44:55:66",
    }
    monkeypatch.setattr(subprocess, "run", _make_run(ip_out, mac_map))

    result = net.get_all_network_interfaces()
    names = [r["interface"] for r in result]
    assert "lo" not in names
    assert "docker0" not in names
    assert "eth0" in names
    assert "enp0s3" in names
    assert len(result) == 2


def test_get_all_network_interfaces_parses_ip_and_mac(monkeypatch):
    ip_out = (
        "2: eth0    inet 192.168.1.10/24 scope global eth0\\       valid_lft forever preferred_lft forever\n"
    )
    monkeypatch.setattr(
        subprocess, "run", _make_run(ip_out, {"eth0": "aa:bb:cc:dd:ee:ff"})
    )

    result = net.get_all_network_interfaces()
    assert result == [
        {"interface": "eth0", "ip": "192.168.1.10", "mac": "AA-BB-CC-DD-EE-FF"}
    ]


def test_get_all_network_interfaces_handles_subprocess_error(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("ip command unavailable")

    monkeypatch.setattr(subprocess, "run", boom)
    assert net.get_all_network_interfaces() == []


def test_get_lan_ip_returns_first_non_filtered(monkeypatch):
    ip_out = (
        "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
        "3: docker0    inet 172.17.0.1/16 scope global docker0\\       valid_lft forever preferred_lft forever\n"
        "2: eth0    inet 192.168.1.10/24 scope global eth0\\       valid_lft forever preferred_lft forever\n"
        "4: enp0s3    inet 10.0.0.5/24 scope global enp0s3\\       valid_lft forever preferred_lft forever\n"
    )
    mac_map = {"eth0": "aa:bb:cc:dd:ee:ff", "enp0s3": "11:22:33:44:55:66"}
    monkeypatch.setattr(subprocess, "run", _make_run(ip_out, mac_map))

    assert net.get_lan_ip() == "192.168.1.10"


def test_get_lan_ip_returns_none_when_no_interfaces(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(subprocess, "run", boom)
    assert net.get_lan_ip() is None
