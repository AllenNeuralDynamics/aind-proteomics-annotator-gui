"""Tests for utils/atomic_io.py."""

import json
from pathlib import Path

import pytest

from aind_proteomics_annotator.utils.atomic_io import atomic_write_json, read_json


def test_round_trip(tmp_path: Path) -> None:
    """Written data can be read back."""
    target = tmp_path / "test.json"
    data = {"key": "value", "num": 42, "list": [1, 2, 3]}
    atomic_write_json(target, data)
    result = read_json(target)
    assert result == data


def test_atomic_write_creates_parent_dirs(tmp_path: Path) -> None:
    """atomic_write_json creates missing intermediate directories."""
    target = tmp_path / "a" / "b" / "c" / "file.json"
    atomic_write_json(target, {"x": 1})
    assert target.exists()


def test_atomic_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    """No .tmp files should remain after a successful write."""
    target = tmp_path / "out.json"
    atomic_write_json(target, {"ok": True})
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Found leftover tmp files: {tmp_files}"


def test_read_json_returns_none_for_missing(tmp_path: Path) -> None:
    """read_json returns None when the file does not exist."""
    result = read_json(tmp_path / "nonexistent.json")
    assert result is None


def test_atomic_write_overwrites_existing(tmp_path: Path) -> None:
    """Writing twice replaces the file contents completely."""
    target = tmp_path / "data.json"
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    result = read_json(target)
    assert result == {"v": 2}


def test_read_json_parses_valid_file(tmp_path: Path) -> None:
    """read_json correctly parses an existing JSON file."""
    target = tmp_path / "valid.json"
    payload = {"hello": "world"}
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert read_json(target) == payload
