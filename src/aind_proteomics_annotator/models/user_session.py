"""Active user session: identity, admin status, and annotation stores."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aind_proteomics_annotator.models.annotation_store import (AnnotationStore,
                                                               FinalLabelStore)
from aind_proteomics_annotator.utils.atomic_io import read_json

if TYPE_CHECKING:
    from aind_proteomics_annotator.models.block_registry import BlockRegistry


class UserSession:
    """Encapsulates the state for the currently logged-in user.

    Annotation data is split into two separate stores:
    - **local**: annotations for datasets browsed from the local filesystem.
      These are never uploaded to S3.
    - **cloud**: annotations for datasets downloaded from S3 into the
      ``cloud_datasets/`` cache.  These are uploaded to S3 on dataset
      switch and on app close.

    The active ``store`` and ``final_label_store`` properties return the
    appropriate store based on the current data root.  Call
    :meth:`switch_data_root` whenever the registry's data root changes.

    Parameters
    ----------
    username:
        The username entered at startup.
    config:
        The application configuration (paths, settings).
    registry:
        The block registry for resolving absolute paths.
    """

    def __init__(self, username: str, config, registry: "BlockRegistry") -> None:
        self.username = username
        self.config = config
        self.is_admin: bool = False
        self._is_cloud_dataset: bool = False

        self._store_local = AnnotationStore(
            filepath=config.user_local_file(username),
            username=username,
            registry=registry,
        )
        self._store_cloud = AnnotationStore(
            filepath=config.user_cloud_file(username),
            username=username,
            registry=registry,
        )
        self._store_final_local = FinalLabelStore(
            config.final_labels_local_file, registry=registry
        )
        self._store_final_cloud = FinalLabelStore(
            config.final_labels_cloud_file, registry=registry
        )

    # ------------------------------------------------------------------
    # Active store properties
    # ------------------------------------------------------------------

    @property
    def store(self) -> AnnotationStore:
        """Return the annotation store for the currently active data root."""
        return self._store_cloud if self._is_cloud_dataset else self._store_local

    @property
    def final_label_store(self) -> FinalLabelStore:
        """Return the final-label store for the currently active data root."""
        return (
            self._store_final_cloud
            if self._is_cloud_dataset
            else self._store_final_local
        )

    # ------------------------------------------------------------------
    # Data-root switching
    # ------------------------------------------------------------------

    def switch_data_root(self, data_root: Path) -> None:
        """Update which store is active based on *data_root*.

        Call this whenever the registry's data root changes (e.g. when the
        user browses to a different dataset).  If *data_root* is inside the
        ``cloud_datasets/`` cache directory, the cloud store becomes active;
        otherwise the local store is active.
        """
        cloud_cache = Path(self.config.s3_local_cache).resolve()
        try:
            Path(data_root).resolve().relative_to(cloud_cache)
            self._is_cloud_dataset = True
        except ValueError:
            self._is_cloud_dataset = False

    # ------------------------------------------------------------------
    # Session initialisation
    # ------------------------------------------------------------------

    def load_or_create(self) -> None:
        """Prepare the session: create directories, load data, check admin."""
        self.config.users_local_dir.mkdir(parents=True, exist_ok=True)
        self.config.users_cloud_dir.mkdir(parents=True, exist_ok=True)
        self.config.display_preferences_dir.mkdir(parents=True, exist_ok=True)
        self.config.admin_local_dir.mkdir(parents=True, exist_ok=True)
        self.config.admin_cloud_dir.mkdir(parents=True, exist_ok=True)

        self._store_local.load_or_create()
        self._store_cloud.load_or_create()
        self._store_final_local.load()
        self._store_final_cloud.load()
        self.is_admin = self._check_admin()

    def _check_admin(self) -> bool:
        roles = read_json(self.config.roles_file)
        if not roles:
            return False
        return self.username in roles.get("admins", [])
