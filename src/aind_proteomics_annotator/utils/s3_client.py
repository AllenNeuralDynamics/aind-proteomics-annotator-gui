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

    def __init__(self, session, profile_name: str = "") -> None:
        self._profile_name = profile_name
        self._session = session
        self._s3 = session.client("s3")

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-create the boto3 session and client from scratch.

        Call this after ``aws sso login`` so the next operation picks up the
        freshly-written SSO token cache without restarting the application.
        """
        import boto3

        self._session = boto3.Session(profile_name=self._profile_name or None)
        self._s3 = self._session.client("s3")

    def _check_auth_error(self, exc: Exception) -> None:
        """Raise a user-friendly RuntimeError when *exc* is an expired-token error."""
        try:
            from botocore import exceptions as be

            sso_types = tuple(
                t
                for name in (
                    "UnauthorizedSSOTokenError",
                    "SSOTokenLoadError",
                    "TokenRetrievalError",
                    "CredentialRetrievalError",
                    "NoCredentialsError",
                )
                if (t := getattr(be, name, None)) is not None
            )
            if sso_types and isinstance(exc, sso_types):
                raise RuntimeError(self._auth_expired_msg()) from exc
            if isinstance(exc, be.ClientError):
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("ExpiredTokenException", "ExpiredToken"):
                    raise RuntimeError(self._auth_expired_msg()) from exc
        except RuntimeError:
            raise
        except Exception:
            pass

    def _auth_expired_msg(self) -> str:
        cmd = "aws sso login"
        if self._profile_name:
            cmd += f" --profile {self._profile_name}"
        return (
            f"AWS credentials have expired.\n\n"
            f"Run the following command in your terminal, then click S3 again:\n\n"
            f"    {cmd}"
        )

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
            self._check_auth_error(exc)
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
            self._check_auth_error(exc)
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
                self._check_auth_error(exc)
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
            self._check_auth_error(exc)
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

        New S3 key format:
          ``<prefix>/users/<username>/<dataset_slug>/<YYYY-MM-DD>.json``

        For each ``(username, dataset_slug)`` pair the lexicographically largest
        date key is selected (latest day).

        Returns
        -------
        dict
            ``{username: {dataset_slug: <parsed annotation dict>}}``
        """
        prefix = output_prefix.rstrip("/") + "/" if output_prefix else ""
        users_prefix = f"{prefix}users/"
        paginator = self._s3.get_paginator("list_objects_v2")
        from collections import defaultdict

        latest: dict[tuple[str, str], str] = {}

        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=users_prefix):
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    # rel: {username}/{dataset_slug}/{YYYY-MM-DD}.json
                    rel = key[len(users_prefix) :]
                    parts = rel.split("/")
                    if len(parts) != 3 or not parts[-1].endswith(".json"):
                        continue
                    username, dataset_slug = parts[0], parts[1]
                    group = (username, dataset_slug)
                    if group not in latest or key > latest[group]:
                        latest[group] = key
        except Exception as exc:
            self._check_auth_error(exc)
            raise RuntimeError(f"Failed to list annotation files: {exc}") from exc

        result: dict[str, dict] = defaultdict(dict)
        for (username, dataset_slug), key in latest.items():
            data = self.download_json(bucket, key)
            if data:
                data["_s3_source_key"] = f"s3://{bucket}/{key}"
                result[username][dataset_slug] = data

        return dict(result)

    def upload_final_labels(self, bucket: str, key: str, data: dict) -> None:
        """Upload admin final-labels JSON to *bucket*/*key*."""
        body = json.dumps(data, indent=2).encode("utf-8")
        try:
            self._s3.put_object(
                Bucket=bucket, Key=key, Body=body, ContentType="application/json"
            )
        except Exception as exc:
            self._check_auth_error(exc)
            raise RuntimeError(
                f"Failed to upload final labels to s3://{bucket}/{key}: {exc}"
            ) from exc

    def get_latest_annotation_key(
        self, bucket: str, output_prefix: str, username: str, dataset_slug: str
    ) -> str:
        """Return the full ``s3://`` URL of the latest annotation file.

        Scans ``{output_prefix}/users/{username}/{dataset_slug}/`` for
        ``*.json`` objects and returns the one with the lexicographically
        largest key (i.e. the most recent date).  Returns ``""`` on any error
        or when no files are found.
        """
        prefix = output_prefix.rstrip("/") + "/"
        search_prefix = f"{prefix}users/{username}/{dataset_slug}/"
        paginator = self._s3.get_paginator("list_objects_v2")
        latest_key = ""
        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=search_prefix):
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    if key.endswith(".json") and key > latest_key:
                        latest_key = key
        except Exception:
            return ""
        return f"s3://{bucket}/{latest_key}" if latest_key else ""

    def download_json(self, bucket: str, key: str) -> Optional[dict]:
        """Download and parse a JSON object; return None on any error."""
        try:
            resp = self._s3.get_object(Bucket=bucket, Key=key)
            return json.loads(resp["Body"].read().decode("utf-8"))
        except Exception:
            return None
