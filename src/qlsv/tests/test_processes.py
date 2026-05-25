"""Tests for qlsv.processes — service whitelist, pgrep probe, status truth table."""
from __future__ import annotations

import subprocess

import pytest

from qlsv import processes
from qlsv.processes import (
    ALLOWED_SERVICES,
    SERVICE_DISPLAY_LABELS,
    SERVICE_PGREP_PATTERNS,
    compute_status,
    is_alive,
    probe_all,
)


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --------------------------------------------------------------------------- #
# compute_status — truth table D-10                                            #
# --------------------------------------------------------------------------- #


def test_compute_status_running_when_alive_regardless_of_expected():
    assert compute_status("bishop", expected_running=False, process_alive=True) == "running"
    assert compute_status("bishop", expected_running=True, process_alive=True) == "running"


def test_compute_status_crashed_when_expected_but_dead():
    assert compute_status("bishop", expected_running=True, process_alive=False) == "crashed"


def test_compute_status_stopped_when_not_expected_and_dead():
    assert compute_status("bishop", expected_running=False, process_alive=False) == "stopped"


# --------------------------------------------------------------------------- #
# is_alive — whitelist + pgrep invocation                                      #
# --------------------------------------------------------------------------- #


def test_is_alive_rejects_unknown_service():
    with pytest.raises(ValueError):
        is_alive("../etc/passwd")
    with pytest.raises(ValueError):
        is_alive("rm -rf /")


def test_is_alive_invokes_pgrep_with_pattern(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(processes.subprocess, "run", fake_run)
    assert is_alive("bishop") is True
    assert captured["cmd"] == ["pgrep", "-f", "bishop_y"]


def test_is_alive_returncode_nonzero_means_dead(monkeypatch):
    def fake_run(cmd, **kwargs):
        return _FakeCompleted(returncode=1)

    monkeypatch.setattr(processes.subprocess, "run", fake_run)
    assert is_alive("goddess") is False


def test_is_alive_swallows_os_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise OSError("pgrep not installed")

    monkeypatch.setattr(processes.subprocess, "run", fake_run)
    assert is_alive("bishop") is False


def test_is_alive_uses_pgrep_pattern_for_wine_binary(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(processes.subprocess, "run", fake_run)
    is_alive("PaySys")
    assert captured["cmd"] == ["pgrep", "-f", "Sword3PaySys.exe"]


# --------------------------------------------------------------------------- #
# probe_all                                                                    #
# --------------------------------------------------------------------------- #


def test_probe_all_returns_six_services(monkeypatch):
    monkeypatch.setattr(processes, "is_alive", lambda svc: True)
    result = probe_all()
    assert len(result) == 6
    assert set(result.keys()) == set(ALLOWED_SERVICES)
    assert all(result.values())


def test_probe_all_preserves_pgrep_pattern_order(monkeypatch):
    monkeypatch.setattr(processes, "is_alive", lambda svc: False)
    result = probe_all()
    assert list(result.keys()) == list(SERVICE_PGREP_PATTERNS.keys())


# --------------------------------------------------------------------------- #
# Constants — guard against accidental drift                                   #
# --------------------------------------------------------------------------- #


def test_allowed_services_exact_six():
    assert ALLOWED_SERVICES == frozenset(
        {"bishop", "goddess", "s3relay", "jx_linux", "PaySys", "RelayServer"}
    )


def test_pgrep_patterns_match_legacy_binaries():
    # Linux ELFs (per 2.3.2/jx.sh:103,123,141,158) end with _y
    assert SERVICE_PGREP_PATTERNS["bishop"] == "bishop_y"
    assert SERVICE_PGREP_PATTERNS["goddess"] == "goddess_y"
    assert SERVICE_PGREP_PATTERNS["s3relay"] == "s3relay_y"
    assert SERVICE_PGREP_PATTERNS["jx_linux"] == "jx_linux_y"
    # Wine processes carry the .exe suffix verbatim (2.3.2/app.py:644-647)
    assert SERVICE_PGREP_PATTERNS["PaySys"] == "Sword3PaySys.exe"
    assert SERVICE_PGREP_PATTERNS["RelayServer"] == "S3RelayServer.exe"


def test_display_labels_match_ui_spec():
    assert SERVICE_DISPLAY_LABELS["PaySys"] == "Sword3PaySys"
    assert SERVICE_DISPLAY_LABELS["RelayServer"] == "S3RelayServer"
    assert SERVICE_DISPLAY_LABELS["bishop"] == "bishop"
