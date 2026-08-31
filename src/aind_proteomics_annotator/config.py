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
    # Dataset slug helpers
    # ------------------------------------------------------------------

    @staticmethod
    def dataset_slug(dataset_key: str) -> str:
        """Convert a slash-separated dataset key to a flat underscore slug.

        Example: ``"Tile_X_0000/ch_561/blocks"`` → ``"Tile_X_0000_ch_561_blocks"``
        """
        return dataset_key.strip("/").replace("/", "_")

    def dataset_key_for_path(self, data_root: Path) -> str:
        """Derive a portable slash-separated dataset key for *data_root*.

        For cloud datasets (path under ``s3_local_cache``), returns the path
        relative to the cache root.  For local datasets, walks up to find the
        experiment root (ancestor whose children include a ``Tile_*`` dir) and
        returns the path relative to that root.  Falls back to the last three
        path components joined with ``/``.
        """
        resolved = Path(data_root).resolve()
        # Cloud: relative to s3_local_cache
        try:
            rel = resolved.relative_to(self.s3_local_cache.resolve())
            return str(rel).replace("\\", "/")
        except ValueError:
            pass
        # Local: walk up to find experiment root
        p = resolved
        for _ in range(6):
            parent = p.parent
            if parent == p:
                break
            try:
                siblings = [d.name for d in parent.iterdir() if d.is_dir()]
                if any(_TILE_RE.search(n) for n in siblings):
                    try:
                        return str(resolved.relative_to(parent)).replace("\\", "/")
                    except ValueError:
                        break
            except OSError:
                break
            p = parent
        # Fallback: last three components
        parts = resolved.parts
        return "/".join(parts[-3:]) if len(parts) >= 3 else resolved.name

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

    def user_dataset_file(
        self, username: str, dataset_key: str, cloud: bool = False
    ) -> Path:
        """Return the per-dataset annotation file path for *username*.

        Nests under the first path component of *dataset_key* (experiment dir):

        ``annotations/users/local/{username}/{experiment}/{rest_slug}.json``  (local)
        ``annotations/users/cloud/{username}/{experiment}/{rest_slug}.json``  (cloud)

        Falls back to a flat ``{slug}.json`` when *dataset_key* has no slash.
        """
        base = self.users_cloud_dir if cloud else self.users_local_dir
        parts = dataset_key.strip("/").split("/", 1)
        if len(parts) == 2:
            experiment, rest = parts
            slug = rest.replace("/", "_")
            return base / username / experiment / f"{slug}.json"
        return base / username / f"{dataset_key.replace('/', '_')}.json"

    def final_labels_file(self, dataset_slug: str, cloud: bool = False) -> Path:
        """Return the admin final-labels file path for *dataset_slug*.

        ``annotations/admin/local/{dataset_slug}_final_labels.json``  (local)
        ``annotations/admin/cloud/{dataset_slug}_final_labels.json``  (cloud)
        """
        base = self.admin_cloud_dir if cloud else self.admin_local_dir
        return base / f"{dataset_slug}_final_labels.json"

    def s3_user_annotation_key(
        self, username: str, dataset_slug: str, date_str: str
    ) -> str:
        """Build the S3 key for a per-user per-dataset annotation upload.

        Format: ``{output_prefix}/users/{username}/{dataset_slug}/{date_str}.json``
        """
        prefix = self.s3_output_prefix.rstrip("/")
        return f"{prefix}/users/{username}/{dataset_slug}/{date_str}.json"

    def s3_admin_final_labels_key(self, dataset_key: str, date_str: str) -> str:
        """Build the S3 key for the admin final-labels file of *dataset_key*.

        Format:
          ``{prefix}/admin/{experiment}/{rest_slug}_{date_str}_final_labels.json``

        where *experiment* is the first path component of *dataset_key* and
        *rest_slug* is the remaining components joined with ``_``.
        """
        prefix = self.s3_output_prefix.rstrip("/")
        parts = dataset_key.strip("/").split("/", 1)
        if len(parts) == 2:
            experiment, rest = parts
            slug = rest.replace("/", "_")
            return f"{prefix}/admin/{experiment}/{slug}_{date_str}_final_labels.json"
        slug = dataset_key.replace("/", "_")
        return f"{prefix}/admin/{slug}_{date_str}_final_labels.json"

    @property
    def display_preferences_dir(self) -> Path:
        return self.annotations_root / "users" / "display_preferences"

    def channel_prefs_file(self, username: str) -> Path:
        """Return the global display-preferences file for *username*.

        Settings apply to all datasets — not scoped to a specific data root.
        """
        return self.display_preferences_dir / f"{username}.json"

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
