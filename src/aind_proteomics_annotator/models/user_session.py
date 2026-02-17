"""Active user session: identity, admin status, and annotation stores."""

from __future__ import annotations

from aind_proteomics_annotator.models.annotation_store import (
    AnnotationStore,
    FinalLabelStore,
)
from aind_proteomics_annotator.utils.atomic_io import read_json


class UserSession:
    """Encapsulates the state for the currently logged-in user.

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
        self.store = AnnotationStore(
            filepath=config.user_file(username),
            username=username,
        )
        self.final_label_store = FinalLabelStore(config.final_labels_file)

    def load_or_create(self) -> None:
        """Prepare the session: create directories, load data, check admin."""
        self.config.users_dir.mkdir(parents=True, exist_ok=True)
        self.config.admin_dir.mkdir(parents=True, exist_ok=True)

        self.store.load_or_create()
        self.final_label_store.load()
        self.is_admin = self._check_admin()

    def _check_admin(self) -> bool:
        roles = read_json(self.config.roles_file)
        if not roles:
            return False
        return self.username in roles.get("admins", [])
