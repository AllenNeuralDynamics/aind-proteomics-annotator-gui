"""Application configuration loaded from environment variables.

All paths default to sensible local values but can be overridden by
environment variables so the same binary works on any machine/mount point:

    ANNOTATOR_DATA_ROOT         Path to the block data directory (default: ./data/blocks)
    ANNOTATOR_ANNOTATIONS_ROOT  Path to the annotations directory (default: ./annotations)
    ANNOTATOR_ROLES_FILE        Path to configs/roles.json (default: ./configs/roles.json)
    ANNOTATOR_CLASSES_FILE      Path to configs/classes.json (default: ./configs/classes.json)

Class definitions (configs/classes.json)
-----------------------------------------
Each entry must have "name" and "color" (hex):

    {
      "classes": [
        {"name": "Class 1", "color": "#22AA44"},
        {"name": "Class 2", "color": "#2266FF"},
        {"name": "Class 3", "color": "#FF6622"}
      ]
    }
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_CLASS_DEFS = [
    {"name": "Class 1", "color": "#22AA44"},
    {"name": "Class 2", "color": "#2266FF"},
    {"name": "Class 3", "color": "#FF6622"},
]


@dataclass
class AppConfig:
    """Centralised application configuration."""

    data_root: Path
    annotations_root: Path
    roles_file: Path
    classes_file: Path
    autoplay_interval_ms: int = 500
    max_cached_blocks: int = 10 # current block + up to 4 preloaded neighbours
    classes: list = field(
        default_factory=lambda: [c["name"] for c in _DEFAULT_CLASS_DEFS]
    )
    class_colors: list = field(
        default_factory=lambda: [c["color"] for c in _DEFAULT_CLASS_DEFS]
    )

    @classmethod
    def from_environment(cls) -> "AppConfig":
        """Build config from environment variables with sensible defaults."""
        roles_file = Path(
            os.environ.get("ANNOTATOR_ROLES_FILE", "./configs/roles.json")
        )
        # Default classes file to the same directory as roles.json so that
        # relative paths set via ANNOTATOR_ROLES_FILE resolve correctly even
        # when the app is launched from a subdirectory (e.g. scripts/).
        default_classes = str(roles_file.parent / "classes.json")
        classes_file = Path(
            os.environ.get("ANNOTATOR_CLASSES_FILE", default_classes)
        )
        class_defs = cls._load_class_defs(classes_file)
        return cls(
            data_root=Path(
                os.environ.get("ANNOTATOR_DATA_ROOT", "./data/blocks")
            ),
            annotations_root=Path(
                os.environ.get("ANNOTATOR_ANNOTATIONS_ROOT", "./annotations")
            ),
            roles_file=roles_file,
            classes_file=classes_file,
            classes=[c["name"] for c in class_defs],
            class_colors=[c["color"] for c in class_defs],
        )

    @staticmethod
    def _load_class_defs(path: Path) -> list:
        """Load class definitions from *path*, falling back to built-in defaults."""
        try:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
                entries = raw.get("classes", [])
                if entries and isinstance(entries[0], dict):
                    return entries
                if entries and isinstance(entries[0], str):
                    # Name-only list — assign default colours
                    return [
                        {
                            "name": n,
                            "color": _DEFAULT_CLASS_DEFS[i]["color"]
                            if i < len(_DEFAULT_CLASS_DEFS)
                            else "#AAAAAA",
                        }
                        for i, n in enumerate(entries)
                    ]
        except Exception:
            pass
        return list(_DEFAULT_CLASS_DEFS)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def label_color_map(self) -> dict:
        """Return {label_int: hex_color} for all configured classes."""
        return {i + 1: color for i, color in enumerate(self.class_colors)}

    @property
    def users_dir(self) -> Path:
        return self.annotations_root / "users"

    @property
    def admin_dir(self) -> Path:
        return self.annotations_root / "admin"

    @property
    def final_labels_file(self) -> Path:
        return self.admin_dir / "final_labels.json"

    def user_file(self, username: str) -> Path:
        return self.users_dir / f"{username}.json"

    def channel_prefs_file(self, username: str) -> Path:
        """Per-user file for persisting channel display preferences (LUT + range)."""
        return self.users_dir / f"{username}_display.json"
