"""Application configuration loaded from environment variables.

All paths default to sensible local values but can be overridden by
environment variables so the same binary works on any machine/mount point:

    ANNOTATOR_DATA_ROOT         Path to the block data directory (default: ./data/blocks)
    ANNOTATOR_ANNOTATIONS_ROOT  Path to the annotations directory (default: ./annotations)
    ANNOTATOR_ROLES_FILE        Path to configs/roles.json (default: ./configs/roles.json)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    """Centralised application configuration."""

    data_root: Path
    annotations_root: Path
    roles_file: Path
    autoplay_interval_ms: int = 2000
    max_cached_blocks: int = 3
    classes: list = field(
        default_factory=lambda: ["Class 1", "Class 2", "Class 3"]
    )

    @classmethod
    def from_environment(cls) -> "AppConfig":
        """Build config from environment variables with sensible defaults."""
        return cls(
            data_root=Path(
                os.environ.get("ANNOTATOR_DATA_ROOT", "./data/blocks")
            ),
            annotations_root=Path(
                os.environ.get("ANNOTATOR_ANNOTATIONS_ROOT", "./annotations")
            ),
            roles_file=Path(
                os.environ.get("ANNOTATOR_ROLES_FILE", "./configs/roles.json")
            ),
        )

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
