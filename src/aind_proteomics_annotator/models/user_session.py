"""Active user session: identity, admin status, and annotation stores."""

from __future__ import annotations

from pathlib import Path

from aind_proteomics_annotator.models.annotation_store import (AnnotationStore,
                                                               FinalLabelStore)
from aind_proteomics_annotator.utils.atomic_io import read_json


class UserSession:
    """Encapsulates the state for the currently logged-in user.

    Annotation data is split into two separate stores based on whether the
    active dataset is a cloud (S3-downloaded) or local dataset.  Each store
    is scoped to a single dataset (identified by a slug derived from the path)
    and is re-created whenever the data root changes.

    Parameters
    ----------
    username:
        The username entered at startup.
    config:
        The application configuration (paths, settings).
    """

    def __init__(self, username: str, config) -> None:
        self.username = username
        self.config = config
        self.is_admin: bool = False
        self._is_cloud_dataset: bool = False
        self._current_dataset_key: str = ""
        self._current_dataset_slug: str = ""

        # Active stores — initialised to empty placeholders; replaced in
        # switch_data_root() once the real data root is known.
        self._store: AnnotationStore = AnnotationStore(
            filepath=config.annotations_root / "_placeholder.json",
            username=username,
        )
        self._store_final: FinalLabelStore = FinalLabelStore(
            filepath=config.annotations_root / "_placeholder_final.json",
        )

    # ------------------------------------------------------------------
    # Active store properties
    # ------------------------------------------------------------------

    @property
    def store(self) -> AnnotationStore:
        """Return the annotation store for the currently active dataset."""
        return self._store

    @property
    def final_label_store(self) -> FinalLabelStore:
        """Return the final-label store for the currently active dataset."""
        return self._store_final

    # ------------------------------------------------------------------
    # Data-root switching
    # ------------------------------------------------------------------

    def switch_data_root(self, data_root: Path) -> None:
        """Create new stores scoped to *data_root*.

        Determines whether the dataset is local or cloud and builds the
        correct file paths using the dataset slug.  Call this whenever the
        registry's data root changes.
        """
        cloud_cache = Path(self.config.s3_local_cache).resolve()
        try:
            Path(data_root).resolve().relative_to(cloud_cache)
            self._is_cloud_dataset = True
        except ValueError:
            self._is_cloud_dataset = False

        dataset_key = self.config.dataset_key_for_path(data_root)
        dataset_slug = self.config.dataset_slug(dataset_key)
        self._current_dataset_key = dataset_key
        self._current_dataset_slug = dataset_slug

        ann_file = self.config.user_dataset_file(
            self.username, dataset_key, cloud=self._is_cloud_dataset
        )
        self._store = AnnotationStore(
            filepath=ann_file,
            username=self.username,
            dataset_key=dataset_key,
            dataset_slug=dataset_slug,
        )
        self._store.load_or_create()

        final_file = self.config.final_labels_file(
            dataset_slug, cloud=self._is_cloud_dataset
        )
        self._store_final = FinalLabelStore(filepath=final_file)
        self._store_final.load()

    # ------------------------------------------------------------------
    # Session initialisation
    # ------------------------------------------------------------------

    def load_or_create(self) -> None:
        """Prepare the session: create directories and check admin status."""
        self.config.users_local_dir.mkdir(parents=True, exist_ok=True)
        self.config.users_cloud_dir.mkdir(parents=True, exist_ok=True)
        self.config.display_preferences_dir.mkdir(parents=True, exist_ok=True)
        self.config.admin_local_dir.mkdir(parents=True, exist_ok=True)
        self.config.admin_cloud_dir.mkdir(parents=True, exist_ok=True)
        self.is_admin = self._check_admin()

    def _check_admin(self) -> bool:
        roles = read_json(self.config.roles_file)
        if not roles:
            return False
        return self.username in roles.get("admins", [])
