"""NFS-safe atomic JSON read/write utilities.

All annotation writes go through this module. The strategy:
  1. Write JSON to a UUID-suffixed temp file in the same directory (same filesystem).
  2. fsync the temp file so data reaches the NFS server before rename.
  3. os.replace() atomically renames temp → target.
  4. fsync the directory fd so the rename is durable on NFS.

Readers use a retry loop to handle transiently stale NFS dentry caches.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional


def atomic_write_json(filepath: Path, data: Any) -> None:
    """Write *data* as JSON to *filepath* atomically.

    Safe for concurrent access from multiple machines on NFS/CIFS.
    The target file is either fully replaced or left untouched on failure.
    """
    filepath = Path(filepath)
    dirpath = filepath.parent
    dirpath.mkdir(parents=True, exist_ok=True)

    # Unique suffix prevents collisions when two processes write concurrently.
    tmp_path = dirpath / f".{filepath.stem}_{uuid.uuid4().hex}.tmp"

    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())  # flush page cache → NFS server

        os.replace(tmp_path, filepath)  # POSIX atomic rename

        # Sync directory so the rename survives a crash on the NFS server.
        try:
            dir_fd = os.open(str(dirpath), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            except OSError:
                # Some networked filesystems return EINVAL for fsync on dir fd.
                pass
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # Non-critical: rename already succeeded

    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def read_json(filepath: Path) -> Optional[Any]:
    """Read JSON from *filepath*, returning None if the file does not exist.

    Retries up to 3 times on transient OSError / JSONDecodeError to handle
    stale NFS dentry caches or in-progress renames on other clients.
    """
    filepath = Path(filepath)
    last_exc: Optional[Exception] = None

    for attempt in range(3):
        try:
            if not filepath.exists():
                return None
            with open(filepath, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))

    raise RuntimeError(
        f"Failed to read {filepath} after 3 attempts"
    ) from last_exc
