"""Shared pytest fixtures."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Return a temp directory pre-populated with two block folders."""
    blocks_root = tmp_path / "data" / "blocks"
    for block_id in ("block_0001", "block_0002"):
        block_dir = blocks_root / block_id
        block_dir.mkdir(parents=True)
        # Create two dummy TIFF-like files (content doesn't matter for registry tests).
        (block_dir / "channel_0.tiff").write_bytes(b"TIFF")
        (block_dir / "channel_1.tiff").write_bytes(b"TIFF")
    return tmp_path


@pytest.fixture
def annotations_dir(tmp_path: Path) -> Path:
    """Return a temp annotations directory with users/ and admin/ sub-dirs."""
    ann = tmp_path / "annotations"
    (ann / "users").mkdir(parents=True)
    (ann / "admin").mkdir(parents=True)
    return ann
