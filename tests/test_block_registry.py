"""Tests for models/block_registry.py."""

from pathlib import Path

import pytest

from aind_proteomics_annotator.models.block_registry import BlockRegistry


def _make_block(root: Path, block_id: str, n_channels: int = 2) -> None:
    block_dir = root / block_id
    block_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n_channels):
        (block_dir / f"channel_{i}.tiff").write_bytes(b"TIFF")


class TestBlockRegistry:
    def test_scan_discovers_blocks(self, tmp_path: Path) -> None:
        root = tmp_path / "blocks"
        _make_block(root, "block_0001")
        _make_block(root, "block_0002")
        registry = BlockRegistry(root)
        registry.scan()
        assert registry.block_count() == 2

    def test_scan_sorts_blocks(self, tmp_path: Path) -> None:
        root = tmp_path / "blocks"
        _make_block(root, "block_0003")
        _make_block(root, "block_0001")
        _make_block(root, "block_0002")
        registry = BlockRegistry(root)
        registry.scan()
        ids = [b.block_id for b in registry.all_blocks()]
        assert ids == ["block_0001", "block_0002", "block_0003"]

    def test_scan_ignores_non_block_dirs(self, tmp_path: Path) -> None:
        root = tmp_path / "blocks"
        _make_block(root, "block_0001")
        (root / "misc_folder").mkdir(parents=True)
        registry = BlockRegistry(root)
        registry.scan()
        assert registry.block_count() == 1

    def test_scan_empty_root(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        registry = BlockRegistry(root)
        registry.scan()
        assert registry.block_count() == 0

    def test_scan_nonexistent_root(self, tmp_path: Path) -> None:
        registry = BlockRegistry(tmp_path / "nonexistent")
        registry.scan()
        assert registry.block_count() == 0

    def test_tiff_files_discovered(self, tmp_path: Path) -> None:
        root = tmp_path / "blocks"
        _make_block(root, "block_0001", n_channels=3)
        registry = BlockRegistry(root)
        registry.scan()
        block = registry.get_block("block_0001")
        assert block is not None
        assert block.channel_count == 3

    def test_get_block_returns_none_for_missing(self, tmp_path: Path) -> None:
        root = tmp_path / "blocks"
        root.mkdir(parents=True)
        registry = BlockRegistry(root)
        registry.scan()
        assert registry.get_block("block_9999") is None
