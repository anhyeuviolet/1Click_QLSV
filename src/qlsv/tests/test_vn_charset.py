"""Tests for qlsv.vn_charset — Vietnamese charset converter.

Behavior-parity tests for the port of the legacy ``Converter`` from
``2.3.2/users.py:455-627``.
"""

import pytest

from qlsv.vn_charset import Converter, myConvert, patterns


def test_patterns_dict_exists():
    assert isinstance(patterns, dict)
    for required in ("TCVN3", "VNI_WIN", "UNICODE"):
        assert required in patterns, f"missing pattern {required!r}"
        pat, flags = patterns[required]
        assert isinstance(pat, str)
        assert isinstance(flags, int)


def test_converter_has_charset_attributes():
    c = Converter()
    for name in ("UNICODE", "TCVN3", "VNI_WIN"):
        assert hasattr(c, name), f"Converter missing attribute {name!r}"
        assert isinstance(getattr(c, name), list)
    # All three lists are the same length (parallel mapping arrays)
    assert len(c.UNICODE) == len(c.TCVN3) == len(c.VNI_WIN)


def test_detect_charset_unicode():
    assert myConvert.detect_charset("Đăng nhập") == "UNICODE"


def test_detect_charset_returns_none_for_ascii():
    assert myConvert.detect_charset("plain ascii") is None


def test_convert_unicode_to_tcvn3_round_trip():
    original = "Đăng nhập"
    tcvn = myConvert.convert(original, "TCVN3", "UNICODE")
    back = myConvert.convert(tcvn, "UNICODE", "TCVN3")
    assert back == original


def test_myconvert_is_singleton_instance():
    assert isinstance(myConvert, Converter)
    # Module-level singleton only — direct ctor calls produce independent objects
    other = Converter()
    assert other is not myConvert


def test_legacy_camelcase_alias_present():
    c = Converter()
    assert hasattr(c, "detectCharset")
    # Delegates to detect_charset — same result for the same input
    assert c.detectCharset("Đăng nhập") == c.detect_charset("Đăng nhập")
