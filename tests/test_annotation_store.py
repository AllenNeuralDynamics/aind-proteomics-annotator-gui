"""Tests for models/annotation_store.py."""

from pathlib import Path

import pytest

from aind_proteomics_annotator.models.annotation_store import (AnnotationStore,
                                                               FinalLabelStore)


class TestAnnotationStore:
    def test_load_or_create_new_file(self, tmp_path: Path) -> None:
        fp = tmp_path / "users" / "alice" / "Tile_X_0000_ch_561_blocks.json"
        store = AnnotationStore(
            fp,
            "alice",
            dataset_key="Tile_X_0000/ch_561/blocks",
            dataset_slug="Tile_X_0000_ch_561_blocks",
        )
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

    def test_block_id_with_path_prefix_stripped(self, tmp_path: Path) -> None:
        """Block IDs like 'some/path/block_0001' use only the last component."""
        fp = tmp_path / "alice.json"
        store = AnnotationStore(fp, "alice")
        store.load_or_create()
        store.set_label("some/path/block_0001", 2)
        assert store.get_label("some/path/block_0001") == 2
        assert store.get_label("block_0001") == 2

    def test_dataset_metadata_stored(self, tmp_path: Path) -> None:
        fp = tmp_path / "alice.json"
        store = AnnotationStore(
            fp,
            "alice",
            dataset_key="Tile_X_0000/ch_561/blocks",
            dataset_slug="Tile_X_0000_ch_561_blocks",
        )
        store.load_or_create()
        import json

        data = json.loads(fp.read_text())
        assert data["dataset_key"] == "Tile_X_0000/ch_561/blocks"
        assert data["dataset_slug"] == "Tile_X_0000_ch_561_blocks"


class TestFinalLabelStore:
    def test_load_empty(self, tmp_path: Path) -> None:
        fp = tmp_path / "Tile_X_0000_ch_561_blocks_final_labels.json"
        store = FinalLabelStore(fp)
        store.load()
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

    def test_all_labels_flat(self, tmp_path: Path) -> None:
        fp = tmp_path / "final_labels.json"
        store = FinalLabelStore(fp)
        store.load()
        store.set_final_label("block_0001", 2, "admin")
        store.set_final_label("block_0002", 1, "admin")
        labels = store.all_labels()
        assert labels["block_0001"]["final_label"] == 2
        assert labels["block_0002"]["final_label"] == 1

    def test_user_annotation_refs(self, tmp_path: Path) -> None:
        fp = tmp_path / "final_labels.json"
        store = FinalLabelStore(fp)
        store.load()
        refs = {"alice": "s3://bucket/annotations/users/alice/slug/2025-01-10.json"}
        store.set_user_annotation_refs(refs)

        store2 = FinalLabelStore(fp)
        store2.load()
        assert store2.get_user_annotation_refs() == refs
