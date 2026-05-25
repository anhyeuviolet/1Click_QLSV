"""Tests for qlsv._atomic — shared atomic JSON write helper (Phase 2 H-6)."""
from __future__ import annotations

import json
import os
import sys

import pytest

from qlsv._atomic import write_json


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 0600 only enforced on POSIX")
def test_write_json_creates_file_mode_0600(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"k": "v"})
    mode = os.stat(target).st_mode & 0o777
    assert oct(mode) == "0o600"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX atomic-write assert")
def test_write_json_atomic_no_tmp_left(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"k": "v"})
    assert not os.path.exists(str(target) + ".tmp")


def test_write_json_round_trip_with_diacritics(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"msg": "Đã lưu cấu hình"})
    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == {"msg": "Đã lưu cấu hình"}
    # ensure_ascii=False — bytes must contain the literal UTF-8 codepoints,
    # not \u-escapes.
    raw = open(target, "rb").read()
    assert "Đã lưu cấu hình".encode("utf-8") in raw


def test_write_json_overwrites_existing(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"v": 1})
    write_json(target, {"v": 2})
    with open(target, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == {"v": 2}


def test_write_json_creates_parent_dir(tmp_path):
    target = tmp_path / "nested" / "dir" / "out.json"
    write_json(target, {"k": "v"})
    assert os.path.exists(target)


@pytest.mark.skipif(sys.platform == "win32", reason="mode arg only meaningful on POSIX")
def test_write_json_custom_mode(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"k": "v"}, mode=0o640)
    mode = os.stat(target).st_mode & 0o777
    assert oct(mode) == "0o640"


def test_write_json_pretty_prints_indent_2(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"a": {"b": 1}})
    text = open(target, "r", encoding="utf-8").read()
    # Trailing newline + 2-space nested indent.
    assert text.endswith("\n")
    assert "\n  " in text
