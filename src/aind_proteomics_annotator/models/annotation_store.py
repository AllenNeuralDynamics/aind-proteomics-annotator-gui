"""File-based JSON annotation storage.

Per-user schema (annotations/users/local/{username}/{dataset_slug}.json):
    {
      "username": "alice",
      "dataset_key": "Tile_X_0000_Y_0003/ch_561/blocks",
      "dataset_slug": "Tile_X_0000_Y_0003_ch_561_blocks",
      "created_at": "<ISO-8601>",
      "updated_at": "<ISO-8601>",
      "annotations": {
        "block_0000": {"label": 1, "annotated_at": "<ISO-8601>"},
        "block_0001": {"label": 2, "annotated_at": "<ISO-8601>"}
      }
    }

Admin schema (annotations/admin/local/{dataset_slug}_final_labels.json):
    {
      "dataset_key": "Tile_X_0000_Y_0003/ch_561/blocks",
      "dataset_slug": "Tile_X_0000_Y_0003_ch_561_blocks",
      "updated_at": "<ISO-8601>",
      "user_annotation_refs": {
        "alice": "s3://bucket/annotations/users/alice/<dataset_slug>/<YYYY-MM-DD>.json",
        "bob":   "s3://bucket/annotations/users/bob/<dataset_slug>/<YYYY-MM-DD>.json"
      },
      "labels": {
        "block_0000": {
          "final_label": 1,
          "set_by": "admin",
          "set_at": "<ISO-8601>"
        }
      }
    }
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aind_proteomics_annotator.utils.atomic_io import (atomic_write_json,
                                                       read_json)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnnotationStore:
    """Manages a single user's annotation JSON file for one dataset.

    The file is scoped to a single dataset (identified by ``dataset_slug``).
    All writes are atomic via atomic_write_json.
    """

    def __init__(
        self,
        filepath: Path,
        username: str,
        dataset_key: str = "",
        dataset_slug: str = "",
    ) -> None:
        self._filepath = Path(filepath)
        self._username = username
        self._dataset_key = dataset_key
        self._dataset_slug = dataset_slug
        self._data: dict = {}

    def load_or_create(self) -> None:
        """Load existing annotation file or create a fresh one."""
        raw = read_json(self._filepath)
        if raw is None:
            self._data = {
                "username": self._username,
                "dataset_key": self._dataset_key,
                "dataset_slug": self._dataset_slug,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "annotations": {},
            }
            self._save()
        else:
            self._data = raw

    def get_label(self, block_id: str) -> Optional[int]:
        """Return the label for *block_id*, or None if not yet annotated."""
        block_name = block_id.split("/")[-1] if "/" in block_id else block_id
        return self._data.get("annotations", {}).get(block_name, {}).get("label")

    def set_label(self, block_id: str, label: int) -> None:
        """Set the label for *block_id* and immediately persist to disk."""
        block_name = block_id.split("/")[-1] if "/" in block_id else block_id
        if "annotations" not in self._data:
            self._data["annotations"] = {}
        self._data["annotations"][block_name] = {
            "label": label,
            "annotated_at": _now_iso(),
        }
        self._data["updated_at"] = _now_iso()
        self._save()

    def all_annotations(self) -> dict:
        """Return a copy of all {block_name: {"label": int, ...}} entries."""
        return dict(self._data.get("annotations", {}))

    def annotated_block_ids(self) -> set:
        """Return the set of block names that have been annotated."""
        return set(self._data.get("annotations", {}).keys())

    def clear_label(self, block_id: str) -> None:
        """Remove the annotation for *block_id* and persist. No-op if absent."""
        block_name = block_id.split("/")[-1] if "/" in block_id else block_id
        annotations = self._data.get("annotations", {})
        if block_name in annotations:
            del annotations[block_name]
            self._data["updated_at"] = _now_iso()
            self._save()

    def _save(self) -> None:
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._filepath, self._data)


class FinalLabelStore:
    """Manages the admin final_labels JSON file for one dataset.

    Only admin users write to this store.  ``user_annotation_refs`` records
    the S3 keys (or local paths) of the per-user annotation files that were
    current at the time the admin reviewed the dataset.
    """

    def __init__(self, filepath: Path) -> None:
        self._filepath = Path(filepath)
        self._data: dict = {"updated_at": _now_iso(), "labels": {}}

    def load(self) -> None:
        """Load existing final labels file if it exists."""
        raw = read_json(self._filepath)
        if raw:
            self._data = raw

    def set_final_label(self, block_id: str, label: int, admin_username: str) -> None:
        """Override the final label for *block_id* and persist to disk."""
        block_name = block_id.split("/")[-1] if "/" in block_id else block_id
        if "labels" not in self._data:
            self._data["labels"] = {}
        self._data["labels"][block_name] = {
            "final_label": label,
            "set_by": admin_username,
            "set_at": _now_iso(),
        }
        self._data["updated_at"] = _now_iso()
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._filepath, self._data)

    def get_final_label(self, block_id: str) -> Optional[int]:
        """Return the admin-set final label for *block_id*, or None."""
        block_name = block_id.split("/")[-1] if "/" in block_id else block_id
        return self._data.get("labels", {}).get(block_name, {}).get("final_label")

    def all_labels(self) -> dict:
        """Return {block_name: {final_label, set_by, set_at}} for all overrides."""
        return dict(self._data.get("labels", {}))

    def set_user_annotation_refs(self, refs: dict) -> None:
        """Record the S3 / local annotation file paths per annotator."""
        self._data["user_annotation_refs"] = refs
        self._data["updated_at"] = _now_iso()
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._filepath, self._data)

    def get_user_annotation_refs(self) -> dict:
        """Return the recorded {username: path} annotation refs, or {}."""
        return dict(self._data.get("user_annotation_refs", {}))
