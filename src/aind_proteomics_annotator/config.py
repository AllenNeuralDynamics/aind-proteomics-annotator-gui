"""Application configuration loaded from environment variables.

All paths default to sensible local values but can be overridden by
environment variables so the same binary works on any machine/mount point:

    ANNOTATOR_DATA_ROOT         Path to the block data directory (default: ./data/blocks)
    ANNOTATOR_ANNOTATIONS_ROOT  Path to the annotations directory (default: ./annotations)
    ANNOTATOR_ROLES_FILE        Path to configs/roles.json (default: ./configs/roles.json)
    ANNOTATOR_CLASSES_FILE      Path to configs/classes.json (default: ./configs/classes.json)

S3 integration (all optional — omit to run in local-only mode):

    ANNOTATOR_S3_DATA_BUCKET    Source S3 bucket containing datasets to annotate.
                                Setting this (or the output bucket) activates S3 features.
    ANNOTATOR_S3_DATA_PREFIX    Optional key prefix within the data bucket (default: "").
    ANNOTATOR_S3_OUTPUT_BUCKET  S3 bucket where annotation JSONs are uploaded.
    ANNOTATOR_S3_OUTPUT_PREFIX  Key prefix for annotations in the output bucket (default: "annotations").
    ANNOTATOR_S3_PROFILE        Optional AWS credentials profile name (default: "").
    ANNOTATOR_S3_LOCAL_CACHE    Explicit directory where S3 datasets are downloaded (optional).
                                If unset, the app walks up from ANNOTATOR_DATA_ROOT to find the
                                experiment-level directory (the ancestor that contains Tile_* siblings)
                                and places a "cloud_datasets/" folder there.

Cloud datasets downloaded from S3 are stored under:
    <experiment_root>/cloud_datasets/   (auto-detected, or ANNOTATOR_S3_LOCAL_CACHE)

Class definitions (configs/classes.json)
-----------------------------------------
Each entry must have "name" and "color" (hex):

    {
      "classes": [
        {"name": "Class 1", "color": "#22AA44"},
        {"name": "Class 2", "color": "#2266FF"},
        {"name": "Class 3", "color": "#FF6622"}
      ],
      "channel_names": [
        "DAPI",
        "NeuN",
        "GFAP"
      ]
    }

If channel_names is omitted, channels are named "Channel 0", "Channel 1", etc.
"""

import json
import os
import re as _re
from dataclasses import dataclass, field
from pathlib import Path

_TILE_RE = _re.compile(r"tile_", _re.IGNORECASE)


def _find_cache_root(data_root: Path) -> Path:
    """Walk up from *data_root* to find the experiment root containing Tile_* dirs.

    Returns that directory joined with "cloud_datasets".  Falls back to
    ``data_root.parent / "cloud_datasets"`` when no tile-containing ancestor
    is found within 6 levels.
    """
    p = Path(data_root).resolve()
    for _ in range(6):
        try:
            children = [d.name for d in p.iterdir() if d.is_dir()]
            if any(_TILE_RE.search(n) for n in children):
                return p / "cloud_datasets"
        except OSError:
            break
        parent = p.parent
        if parent == p:
            break
        p = parent
    return Path(data_root).resolve().parent / "cloud_datasets"


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
    autoplay_interval_ms: int = 100
    max_cached_blocks: int = 10
    classes: list = field(
        default_factory=lambda: [c["name"] for c in _DEFAULT_CLASS_DEFS]
    )
    class_colors: list = field(
        default_factory=lambda: [c["color"] for c in _DEFAULT_CLASS_DEFS]
    )
    channel_names: list = field(default_factory=list)

    # S3 fields — all default to empty/disabled.
    s3_data_bucket: str = ""
    s3_data_prefix: str = ""
    s3_output_bucket: str = ""
    s3_output_prefix: str = "annotations"
    s3_profile: str = ""
    s3_local_cache_override: str = ""

    @classmethod
    def from_environment(cls) -> "AppConfig":
        """Build config from environment variables with sensible defaults."""
        roles_file = Path(
            os.environ.get("ANNOTATOR_ROLES_FILE", "./configs/roles.json")
        )
        default_classes = str(roles_file.parent / "classes.json")
        classes_file = Path(os.environ.get("ANNOTATOR_CLASSES_FILE", default_classes))
        class_defs, channel_names = cls._load_config_file(classes_file)
        return cls(
            data_root=Path(os.environ.get("ANNOTATOR_DATA_ROOT", "./data/blocks")),
            annotations_root=Path(
                os.environ.get("ANNOTATOR_ANNOTATIONS_ROOT", "./annotations")
            ),
            roles_file=roles_file,
            classes_file=classes_file,
            classes=[c["name"] for c in class_defs],
            class_colors=[c["color"] for c in class_defs],
            channel_names=channel_names,
            s3_data_bucket=os.environ.get("ANNOTATOR_S3_DATA_BUCKET", ""),
            s3_data_prefix=os.environ.get("ANNOTATOR_S3_DATA_PREFIX", ""),
            s3_output_bucket=os.environ.get("ANNOTATOR_S3_OUTPUT_BUCKET", ""),
            s3_output_prefix=os.environ.get(
                "ANNOTATOR_S3_OUTPUT_PREFIX", "annotations"
            ),
            s3_profile=os.environ.get("ANNOTATOR_S3_PROFILE", ""),
            s3_local_cache_override=os.environ.get("ANNOTATOR_S3_LOCAL_CACHE", ""),
        )

    @staticmethod
    def _load_config_file(path: Path) -> tuple[list, list]:
        """Load class definitions and channel names from *path*.

        Returns (class_defs, channel_names), falling back to built-in defaults.
        """
        channel_names = []
        try:
            if path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))

                if "channel_names" in raw and isinstance(raw["channel_names"], list):
                    channel_names = raw["channel_names"]

                entries = raw.get("classes", [])
                if entries and isinstance(entries[0], dict):
                    return entries, channel_names
                if entries and isinstance(entries[0], str):
                    class_defs = [
                        {
                            "name": n,
                            "color": (
                                _DEFAULT_CLASS_DEFS[i]["color"]
                                if i < len(_DEFAULT_CLASS_DEFS)
                                else "#AAAAAA"
                            ),
                        }
                        for i, n in enumerate(entries)
                    ]
                    return class_defs, channel_names
        except Exception:
            pass
        return list(_DEFAULT_CLASS_DEFS), channel_names

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def label_color_map(self) -> dict:
        """Return {label_int: hex_color} for all configured classes."""
        return {i + 1: color for i, color in enumerate(self.class_colors)}

    def get_channel_name(self, index: int) -> str:
        if index < len(self.channel_names):
            return self.channel_names[index]
        return f"Channel {index}"

    # ------------------------------------------------------------------
    # Annotation directory structure (local vs cloud)
    # ------------------------------------------------------------------

    @property
    def users_local_dir(self) -> Path:
        return self.annotations_root / "users" / "local"

    @property
    def users_cloud_dir(self) -> Path:
        return self.annotations_root / "users" / "cloud"

    @property
    def admin_local_dir(self) -> Path:
        return self.annotations_root / "admin" / "local"

    @property
    def admin_cloud_dir(self) -> Path:
        return self.annotations_root / "admin" / "cloud"

    def user_local_file(self, username: str) -> Path:
        return self.users_local_dir / f"{username}.json"

    def user_cloud_file(self, username: str) -> Path:
        return self.users_cloud_dir / f"{username}.json"

    @property
    def display_preferences_dir(self) -> Path:
        return self.annotations_root / "users" / "display_preferences"

    def channel_prefs_file(self, username: str) -> Path:
        """Return the global display-preferences file for *username*.

        Settings apply to all datasets — not scoped to a specific data root.
        """
        return self.display_preferences_dir / f"{username}.json"

    @property
    def final_labels_local_file(self) -> Path:
        return self.admin_local_dir / "final_labels.json"

    @property
    def final_labels_cloud_file(self) -> Path:
        return self.admin_cloud_dir / "final_labels.json"

    # ------------------------------------------------------------------
    # S3 helpers
    # ------------------------------------------------------------------

    @property
    def s3_enabled(self) -> bool:
        """True when at least one S3 bucket is configured."""
        return bool(self.s3_data_bucket or self.s3_output_bucket)

    @property
    def s3_local_cache(self) -> Path:
        """Root directory for S3-downloaded datasets.

        Uses ``ANNOTATOR_S3_LOCAL_CACHE`` if set; otherwise walks up from
        ``data_root`` to find the experiment root (the ancestor that contains
        ``Tile_*`` siblings) and appends ``cloud_datasets`` there.
        """
        if self.s3_local_cache_override:
            return Path(self.s3_local_cache_override)
        return _find_cache_root(self.data_root)
