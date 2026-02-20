"""File-based JSON annotation storage.

Per-user schema (annotations/users/{username}.json):
    {
      "username": "alice",
      "created_at": "<ISO-8601>",
      "updated_at": "<ISO-8601>",
      "annotations": {
        "/absolute/path/to/parent": {
          "block_0000": {"label": 1, "annotated_at": "<ISO-8601>"},
          "block_0001": {"label": 2, "annotated_at": "<ISO-8601>"}
        }
      }
    }

Admin schema (annotations/admin/final_labels.json):
    {
      "updated_at": "<ISO-8601>",
      "labels": {
        "/absolute/path/to/parent": {
          "block_0000": {
            "final_label": 1,
            "set_by": "admin",
            "set_at": "<ISO-8601>"
          }
        }
      }
    }
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from aind_proteomics_annotator.utils.atomic_io import atomic_write_json, read_json

if TYPE_CHECKING:
    from aind_proteomics_annotator.models.block_registry import BlockRegistry


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnnotationStore:
    """Manages a single user's annotation JSON file.

    All writes are atomic via atomic_write_json, making this safe for
    shared filesystem access from multiple machines.
    """

    def __init__(
        self, filepath: Path, username: str, registry: Optional["BlockRegistry"] = None
    ) -> None:
        self._filepath = Path(filepath)
        self._username = username
        self._registry = registry
        self._data: dict = {}

    def _get_storage_key(self, block_id: str) -> tuple[str, str]:
        """Return (absolute_parent_path, block_name) for storage.

        If registry is available, uses it to get the absolute parent path.
        Otherwise falls back to parsing the block_id.
        """
        if self._registry:
            absolute_parent = self._registry.get_absolute_parent_path(block_id)
            # Extract block name from block_id
            block_name = block_id.split("/")[-1] if "/" in block_id else block_id
            return absolute_parent, block_name
        else:
            # Fallback: parse block_id as relative path
            if "/" in block_id:
                parts = block_id.rsplit("/", 1)
                return parts[0], parts[1]
            return "", block_id

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
        parent_path, block_name = self._get_storage_key(block_id)
        return (
            self._data.get("annotations", {})
            .get(parent_path, {})
            .get(block_name, {})
            .get("label")
        )

    def set_label(self, block_id: str, label: int) -> None:
        """Set the label for *block_id* and immediately persist to disk."""
        parent_path, block_name = self._get_storage_key(block_id)
        if "annotations" not in self._data:
            self._data["annotations"] = {}
        if parent_path not in self._data["annotations"]:
            self._data["annotations"][parent_path] = {}
        self._data["annotations"][parent_path][block_name] = {
            "label": label,
            "annotated_at": _now_iso(),
        }
        self._data["updated_at"] = _now_iso()
        self._save()

    def all_annotations(self) -> dict:
        """Return a copy of all {block_id: {"label": int, ...}} entries.

        Flattens the nested structure back into a flat dictionary.
        """
        result = {}
        annotations = self._data.get("annotations", {})
        for parent_path, blocks in annotations.items():
            for block_name, data in blocks.items():
                # Reconstruct block_id from parent_path and block_name
                if parent_path:
                    block_id = f"{parent_path}/{block_name}"
                else:
                    block_id = block_name
                result[block_id] = data
        return result

    def annotated_block_ids(self) -> set:
        """Return the set of block IDs that have been annotated."""
        result = set()
        annotations = self._data.get("annotations", {})
        for parent_path, blocks in annotations.items():
            for block_name in blocks.keys():
                if parent_path:
                    result.add(f"{parent_path}/{block_name}")
                else:
                    result.add(block_name)
        return result

    def clear_label(self, block_id: str) -> None:
        """Remove the annotation for *block_id* and persist. No-op if absent."""
        parent_path, block_name = self._get_storage_key(block_id)
        annotations = self._data.get("annotations", {})
        if parent_path in annotations and block_name in annotations[parent_path]:
            del annotations[parent_path][block_name]
            # Clean up empty parent path dictionaries
            if not annotations[parent_path]:
                del annotations[parent_path]
            self._data["updated_at"] = _now_iso()
            self._save()

    def _save(self) -> None:
        atomic_write_json(self._filepath, self._data)


class FinalLabelStore:
    """Manages the admin/final_labels.json file.

    Only admin users write to this store.
    Stores labels keyed by absolute parent path.
    """

    def __init__(
        self, filepath: Path, registry: Optional["BlockRegistry"] = None
    ) -> None:
        self._filepath = Path(filepath)
        self._registry = registry
        self._data: dict = {"updated_at": _now_iso(), "labels": {}}

    def load(self) -> None:
        """Load existing final labels file if it exists."""
        raw = read_json(self._filepath)
        if raw:
            self._data = raw

    def _get_storage_key(self, block_id: str) -> tuple[str, str]:
        """Return (absolute_parent_path, block_name) for storage.

        If registry is available, uses it to get the absolute parent path.
        Otherwise falls back to parsing the block_id.
        """
        if self._registry:
            absolute_parent = self._registry.get_absolute_parent_path(block_id)
            # Extract block name from block_id
            block_name = block_id.split("/")[-1] if "/" in block_id else block_id
            return absolute_parent, block_name
        else:
            # Fallback: parse block_id as relative path
            if "/" in block_id:
                parts = block_id.rsplit("/", 1)
                return parts[0], parts[1]
            return "", block_id

    def set_final_label(
        self, block_id: str, label: int, admin_username: str
    ) -> None:
        """Override the final label for *block_id* and persist to disk."""
        parent_path, block_name = self._get_storage_key(block_id)
        if "labels" not in self._data:
            self._data["labels"] = {}
        if parent_path not in self._data["labels"]:
            self._data["labels"][parent_path] = {}
        self._data["labels"][parent_path][block_name] = {
            "final_label": label,
            "set_by": admin_username,
            "set_at": _now_iso(),
        }
        self._data["updated_at"] = _now_iso()
        atomic_write_json(self._filepath, self._data)

    def get_final_label(self, block_id: str) -> Optional[int]:
        """Return the admin-set final label for *block_id*, or None."""
        parent_path, block_name = self._get_storage_key(block_id)
        return (
            self._data.get("labels", {})
            .get(parent_path, {})
            .get(block_name, {})
            .get("final_label")
        )

    def all_labels(self) -> dict:
        """Return a copy of all {block_id: {...}} final label entries.

        Flattens the nested structure back into a flat dictionary.
        """
        result = {}
        labels = self._data.get("labels", {})
        for parent_path, blocks in labels.items():
            for block_name, data in blocks.items():
                # Reconstruct block_id from parent_path and block_name
                if parent_path:
                    block_id = f"{parent_path}/{block_name}"
                else:
                    block_id = block_name
                result[block_id] = data
        return result
