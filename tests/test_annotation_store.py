"""Tests for models/annotation_store.py."""

from pathlib import Path

import pytest

from aind_proteomics_annotator.models.annotation_store import (
    AnnotationStore,
    FinalLabelStore,
)


class TestAnnotationStore:
    def test_load_or_create_new_file(self, tmp_path: Path) -> None:
        """A fresh store creates the file and returns empty annotations."""
        fp = tmp_path / "users" / "alice.json"
        store = AnnotationStore(fp, "alice")
        store.load_or_create()
        assert fp.exists()
        assert store.annotated_block_ids() == set()

    def test_set_and_get_label(self, tmp_path: Path) -> None:
        fp = tmp_path / "alice.json"
        store = AnnotationStore(fp, "alice")
        store.load_or_create()
        store.set_label("block_0001", 2)
        assert store.get_label("block_0001") == 2

    def test_get_label_returns_none_for_unannotated(self, tmp_path: Path) -> None:
        fp = tmp_path / "alice.json"
        store = AnnotationStore(fp, "alice")
        store.load_or_create()
        assert store.get_label("block_9999") is None

    def test_annotated_block_ids(self, tmp_path: Path) -> None:
        fp = tmp_path / "alice.json"
        store = AnnotationStore(fp, "alice")
        store.load_or_create()
        store.set_label("block_0001", 1)
        store.set_label("block_0002", 3)
        assert store.annotated_block_ids() == {"block_0001", "block_0002"}

    def test_all_annotations(self, tmp_path: Path) -> None:
        fp = tmp_path / "alice.json"
        store = AnnotationStore(fp, "alice")
        store.load_or_create()
        store.set_label("block_0001", 1)
        anns = store.all_annotations()
        assert "block_0001" in anns
        assert anns["block_0001"]["label"] == 1

    def test_label_persists_across_instances(self, tmp_path: Path) -> None:
        """Setting a label should persist when the store is reloaded."""
        fp = tmp_path / "alice.json"
        store1 = AnnotationStore(fp, "alice")
        store1.load_or_create()
        store1.set_label("block_0001", 3)

        store2 = AnnotationStore(fp, "alice")
        store2.load_or_create()
        assert store2.get_label("block_0001") == 3

    def test_set_label_overwrites(self, tmp_path: Path) -> None:
        fp = tmp_path / "alice.json"
        store = AnnotationStore(fp, "alice")
        store.load_or_create()
        store.set_label("block_0001", 1)
        store.set_label("block_0001", 2)
        assert store.get_label("block_0001") == 2


class TestFinalLabelStore:
    def test_load_empty(self, tmp_path: Path) -> None:
        fp = tmp_path / "final_labels.json"
        store = FinalLabelStore(fp)
        store.load()  # file doesn't exist yet
        assert store.all_labels() == {}

    def test_set_and_get_final_label(self, tmp_path: Path) -> None:
        fp = tmp_path / "final_labels.json"
        store = FinalLabelStore(fp)
        store.load()
        store.set_final_label("block_0001", 2, "admin")
        assert store.get_final_label("block_0001") == 2

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        fp = tmp_path / "final_labels.json"
        FinalLabelStore(fp).set_final_label("block_0001", 1, "admin")

        store2 = FinalLabelStore(fp)
        store2.load()
        assert store2.get_final_label("block_0001") == 1

    def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        fp = tmp_path / "final_labels.json"
        store = FinalLabelStore(fp)
        store.load()
        assert store.get_final_label("block_9999") is None
