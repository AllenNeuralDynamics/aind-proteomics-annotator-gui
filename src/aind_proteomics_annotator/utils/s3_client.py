"""Thin boto3 wrapper for S3 operations used by the annotator tool.

All public methods raise RuntimeError on failure so callers can show
user-friendly messages without catching botocore internals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional


class S3Client:
    """Wraps a boto3 Session with the operations the annotator needs."""

    def __init__(self, session) -> None:
        self._session = session
        self._s3 = session.client("s3")

    # ------------------------------------------------------------------
    # Connection / credential check
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """Return True when the credentials are valid (can call list_buckets)."""
        try:
            self._s3.list_buckets()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Dataset discovery
    # ------------------------------------------------------------------

    def list_datasets(self, bucket: str, prefix: str) -> list[str]:
        """Return sorted list of ``blocks/``-level S3 key prefixes.

        Scans all objects under *bucket*/*prefix* and collects any prefix
        component named ``blocks``, returning the full prefix including the
        trailing slash (e.g. ``"Tile_X_0000.../ch_561/blocks/"``).
        """
        prefix = prefix.rstrip("/") + "/" if prefix else ""
        paginator = self._s3.get_paginator("list_objects_v2")
        blocks_prefixes: set[str] = set()
        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    # Strip the data prefix to get the relative key.
                    rel = key[len(prefix) :]
                    parts = rel.split("/")
                    for i, part in enumerate(parts):
                        if part == "blocks":
                            blocks_key = prefix + "/".join(parts[: i + 1]) + "/"
                            blocks_prefixes.add(blocks_key)
                            break
        except Exception as exc:
            raise RuntimeError(
                f"Failed to list datasets from s3://{bucket}/{prefix}: {exc}"
            ) from exc
        return sorted(blocks_prefixes)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_blocks_dir(
        self,
        bucket: str,
        s3_prefix: str,
        local_dir: Path,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancelled_flag: Optional[list] = None,
    ) -> None:
        """Download every object under *s3_prefix* into *local_dir*.

        Parameters
        ----------
        bucket:
            S3 bucket name.
        s3_prefix:
            Full S3 key prefix (with trailing slash) for the blocks directory.
        local_dir:
            Destination directory; created if it does not exist.
        progress_cb:
            Optional ``(done, total)`` callback called after each file.
        cancelled_flag:
            A one-element list ``[False]``; set ``cancelled_flag[0] = True``
            from another thread to abort the download.
        """
        s3_prefix = s3_prefix.rstrip("/") + "/"
        paginator = self._s3.get_paginator("list_objects_v2")

        # Collect all keys first so we can report accurate totals.
        keys: list[str] = []
        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=s3_prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
        except Exception as exc:
            raise RuntimeError(f"Failed to list objects for download: {exc}") from exc

        total = len(keys)
        local_dir = Path(local_dir)
        for done, key in enumerate(keys, start=1):
            if cancelled_flag and cancelled_flag[0]:
                return
            rel = key[len(s3_prefix) :]
            if not rel:
                continue
            dest = local_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._s3.download_file(bucket, key, str(dest))
            except Exception as exc:
                raise RuntimeError(f"Failed to download {key}: {exc}") from exc
            if progress_cb:
                progress_cb(done, total)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_annotation_json(self, bucket: str, key: str, data: dict) -> None:
        """Serialize *data* as JSON and upload to *bucket*/*key*."""
        body = json.dumps(data, indent=2).encode("utf-8")
        try:
            self._s3.put_object(
                Bucket=bucket, Key=key, Body=body, ContentType="application/json"
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to upload annotations to s3://{bucket}/{key}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Admin: load latest annotations from all users
    # ------------------------------------------------------------------

    def load_all_latest_annotations(
        self, bucket: str, output_prefix: str
    ) -> dict[str, dict]:
        """Download the most-recent annotation file for every user+dataset.

        Scans ``s3://<bucket>/<output_prefix>/<username>/.../<YYYY-MM-DD>.json``
        and for each ``(username, dataset_path)`` pair selects the
        lexicographically largest date key (latest day).

        Returns
        -------
        dict
            ``{username: {dataset_key: <parsed annotation dict>}}``
        """
        output_prefix = output_prefix.rstrip("/") + "/" if output_prefix else ""
        paginator = self._s3.get_paginator("list_objects_v2")

        # Collect all annotation keys grouped by (username, dataset_path).
        # Key format: <prefix>/<username>/<dataset_path...>/<YYYY-MM-DD>.json
        from collections import defaultdict

        latest: dict[tuple[str, str], str] = {}

        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=output_prefix):
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    rel = key[len(output_prefix) :]
                    parts = rel.split("/")
                    if len(parts) < 2 or not parts[-1].endswith(".json"):
                        continue
                    username = parts[0]
                    # dataset_path = everything between username and the date file
                    dataset_path = "/".join(parts[1:-1])
                    group = (username, dataset_path)
                    if group not in latest or key > latest[group]:
                        latest[group] = key
        except Exception as exc:
            raise RuntimeError(f"Failed to list annotation files: {exc}") from exc

        # Download and parse each latest file.
        result: dict[str, dict] = defaultdict(dict)
        for (username, dataset_path), key in latest.items():
            data = self.download_json(bucket, key)
            if data:
                result[username][dataset_path] = data

        return dict(result)

    def download_json(self, bucket: str, key: str) -> Optional[dict]:
        """Download and parse a JSON object; return None on any error."""
        try:
            resp = self._s3.get_object(Bucket=bucket, Key=key)
            return json.loads(resp["Body"].read().decode("utf-8"))
        except Exception:
            return None
