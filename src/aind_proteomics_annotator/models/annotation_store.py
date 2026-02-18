"""File-based JSON annotation storage.

Per-user schema (annotations/users/{username}.json):
    {
      "username": "alice",
      "created_at": "<ISO-8601>",
      "updated_at": "<ISO-8601>",
      "annotations": {
        "block_0001": {"label": 1, "annotated_at": "<ISO-8601>"}
      }
    }

Admin schema (annotations/admin/final_labels.json):
    {
      "updated_at": "<ISO-8601>",
      "labels": {
        "block_0001": {
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

from aind_proteomics_annotator.utils.atomic_io import atomic_write_json, read_json


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnnotationStore:
    """Manages a single user's annotation JSON file.

    All writes are atomic via atomic_write_json, making this safe for
    shared filesystem access from multiple machines.
    """

    def __init__(self, filepath: Path, username: str) -> None:
        self._filepath = Path(filepath)
        self._username = username
        self._data: dict = {}

    def load_or_create(self) -> None:
        """Load existing annotation file or create a fresh one."""
        raw = read_json(self._filepath)
        if raw is None:
            self._data = {
                "username": self._username,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "annotations": {},
            }
            self._save()
        else:
            self._data = raw

    def get_label(self, block_id: str) -> Optional[int]:
        """Return the label for *block_id*, or None if not yet annotated."""
        return self._data.get("annotations", {}).get(block_id, {}).get("label")

    def set_label(self, block_id: str, label: int) -> None:
        """Set the label for *block_id* and immediately persist to disk."""
        if "annotations" not in self._data:
            self._data["annotations"] = {}
        self._data["annotations"][block_id] = {
            "label": label,
            "annotated_at": _now_iso(),
        }
        self._data["updated_at"] = _now_iso()
        self._save()

    def all_annotations(self) -> dict:
        """Return a copy of all {block_id: {"label": int, ...}} entries."""
        return dict(self._data.get("annotations", {}))

    def annotated_block_ids(self) -> set:
        """Return the set of block IDs that have been annotated."""
        return set(self._data.get("annotations", {}).keys())

    def clear_label(self, block_id: str) -> None:
        """Remove the annotation for *block_id* and persist. No-op if absent."""
        if block_id in self._data.get("annotations", {}):
            del self._data["annotations"][block_id]
            self._data["updated_at"] = _now_iso()
            self._save()

    def _save(self) -> None:
        atomic_write_json(self._filepath, self._data)


class FinalLabelStore:
    """Manages the admin/final_labels.json file.

    Only admin users write to this store.
    """

    def __init__(self, filepath: Path) -> None:
        self._filepath = Path(filepath)
        self._data: dict = {"updated_at": _now_iso(), "labels": {}}

    def load(self) -> None:
        """Load existing final labels file if it exists."""
        raw = read_json(self._filepath)
        if raw:
            self._data = raw

    def set_final_label(
        self, block_id: str, label: int, admin_username: str
    ) -> None:
        """Override the final label for *block_id* and persist to disk."""
        if "labels" not in self._data:
            self._data["labels"] = {}
        self._data["labels"][block_id] = {
            "final_label": label,
            "set_by": admin_username,
            "set_at": _now_iso(),
        }
        self._data["updated_at"] = _now_iso()
        atomic_write_json(self._filepath, self._data)

    def get_final_label(self, block_id: str) -> Optional[int]:
        """Return the admin-set final label for *block_id*, or None."""
        return self._data.get("labels", {}).get(block_id, {}).get("final_label")

    def all_labels(self) -> dict:
        """Return a copy of all {block_id: {...}} final label entries."""
        return dict(self._data.get("labels", {}))
