"""Dialog for browsing S3 datasets, showing cache status, and downloading.

The dialog lists all ``blocks/`` prefixes found under the configured S3 data
bucket/prefix.  Datasets already present in the local cache are shown in green
with a "✓" prefix; uncached datasets show in white.

Workflow
--------
1. Dialog opens → listing worker starts asynchronously.
2. User selects one or more datasets:
   - Single cached  → "Open →" button enabled immediately.
   - Single uncached → "Download & Open" button enabled.
   - Multiple, all cached → "Open First →" button enabled.
   - Multiple, any uncached → "Download Selected (N)" button enabled.
3. User clicks the action button:
   - Cached only  → ``dataset_ready`` signal fires and dialog closes.
   - Download     → datasets are queued and downloaded sequentially; progress
                    label shows "Dataset M / N"; dialog stays open when done.
4. "Download All" button queues every uncached dataset in one click.
5. After a batch download the user selects whichever row they want to open and
   clicks "Open →".

Thread lifecycle
----------------
Both workers follow the standard Qt pattern:
  - ``QThread`` has **no parent** so Qt does not destroy it when the dialog
    closes.
  - ``worker.finished / worker.error → thread.quit`` stops the thread's event
    loop when the worker is done.
  - ``thread.finished → thread.deleteLater, worker.deleteLater`` cleans up
    both objects after the OS thread exits.
  - ``closeEvent`` sets the cancellation flag and calls ``thread.quit()`` /
    ``thread.wait()`` so the OS thread has exited before the dialog object is
    destroyed, avoiding the "Destroyed while thread is still running" crash.
"""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import QObject, Qt, QThread, QTimer, Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                            QListWidget, QListWidgetItem, QProgressBar,
                            QPushButton, QVBoxLayout)


class _ListWorker(QObject):
    """Lists datasets from S3 in a background thread."""

    finished = Signal(list)
    error = Signal(str)

    def __init__(self, s3_client, bucket: str, prefix: str) -> None:
        super().__init__()
        self._client = s3_client
        self._bucket = bucket
        self._prefix = prefix

    def run(self) -> None:
        try:
            datasets = self._client.list_datasets(self._bucket, self._prefix)
            self.finished.emit(datasets)
        except Exception as exc:
            self.error.emit(str(exc))


class _DownloadWorker(QObject):
    """Downloads a blocks/ directory from S3 in a background thread."""

    progress = Signal(int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        s3_client,
        bucket: str,
        s3_prefix: str,
        local_dir: Path,
        cancelled_flag: list,
    ) -> None:
        super().__init__()
        self._client = s3_client
        self._bucket = bucket
        self._s3_prefix = s3_prefix
        self._local_dir = local_dir
        self._cancelled = cancelled_flag

    def run(self) -> None:
        try:
            self._client.download_blocks_dir(
                self._bucket,
                self._s3_prefix,
                self._local_dir,
                progress_cb=self.progress.emit,
                cancelled_flag=self._cancelled,
            )
            if not self._cancelled[0]:
                self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


def _make_thread(worker: QObject) -> QThread:
    """Create a parentless QThread with proper cleanup connections."""
    thread = QThread()  # no parent — dialog destruction won't kill the thread
    worker.moveToThread(thread)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(worker.deleteLater)
    return thread


class S3DatasetDialog(QDialog):
    """Dataset browser and downloader for S3-hosted block data.

    Signals
    -------
    dataset_ready : str
        Emitted with the absolute local path to the blocks/ directory after a
        dataset is selected (cached) or successfully downloaded.
    """

    dataset_ready = Signal(str)

    def __init__(self, s3_client, config, parent=None) -> None:
        super().__init__(parent)
        self._client = s3_client
        self._config = config
        self._datasets: list[str] = []
        self._cancelled = [False]
        self._download_thread: QThread | None = None
        self._list_thread: QThread | None = None
        self._closing = False

        # Sequential download queue: list of (s3_prefix, local_path_str)
        self._download_queue: list[tuple[str, str]] = []
        self._queue_done: int = 0
        self._queue_total: int = 0

        self.setWindowTitle("S3 Datasets")
        self.setModal(True)
        self.setMinimumSize(640, 420)
        self._build_ui()
        self._start_listing()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(
            QLabel("Available datasets (Ctrl/Shift+click to select multiple):")
        )

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, stretch=1)

        self._status_label = QLabel("Fetching dataset list from S3…")
        self._status_label.setStyleSheet("font-size: 11px; color: #AAAAAA;")
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        btn_row = QHBoxLayout()

        self._download_all_btn = QPushButton("Download All")
        self._download_all_btn.setEnabled(False)
        self._download_all_btn.setToolTip(
            "Download all uncached datasets sequentially."
        )
        self._download_all_btn.clicked.connect(self._on_download_all_clicked)
        btn_row.addWidget(self._download_all_btn)

        self._redownload_btn = QPushButton("Re-download")
        self._redownload_btn.setEnabled(False)
        self._redownload_btn.setToolTip(
            "Force a fresh download, overwriting the local cache."
        )
        self._redownload_btn.clicked.connect(self._on_redownload_clicked)
        btn_row.addWidget(self._redownload_btn)

        btn_row.addStretch()

        open_local_btn = QPushButton("Open Local…")
        open_local_btn.setToolTip("Open a local blocks/ directory (bypasses S3).")
        open_local_btn.clicked.connect(self._on_open_local)
        btn_row.addWidget(open_local_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)

        self._open_btn = QPushButton("Open →")
        self._open_btn.setEnabled(False)
        self._open_btn.setDefault(True)
        self._open_btn.clicked.connect(self._on_open_clicked)
        btn_row.addWidget(self._open_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Dataset listing
    # ------------------------------------------------------------------

    def _start_listing(self) -> None:
        worker = _ListWorker(
            self._client,
            self._config.s3_data_bucket,
            self._config.s3_data_prefix,
        )
        thread = _make_thread(worker)
        worker.finished.connect(self._on_datasets_listed)
        worker.error.connect(self._on_list_error)
        thread.started.connect(worker.run)
        # Null out the reference once the thread finishes so closeEvent
        # doesn't try to call methods on an already-deleted C++ object.
        thread.finished.connect(lambda: setattr(self, "_list_thread", None))
        thread.start()
        self._list_thread = thread
        self._list_worker = worker

    def _on_datasets_listed(self, datasets: list) -> None:
        if self._closing:
            return
        self._datasets = datasets
        self._list.clear()
        cache_root = self._config.s3_local_cache
        data_prefix = (
            self._config.s3_data_prefix.rstrip("/") + "/"
            if self._config.s3_data_prefix
            else ""
        )

        uncached_count = 0
        for s3_prefix in datasets:
            rel = (
                s3_prefix[len(data_prefix) :].strip("/")
                if data_prefix
                else s3_prefix.strip("/")
            )
            local_path = cache_root / rel
            cached = (
                local_path.exists() and any(local_path.iterdir())
                if local_path.exists()
                else False
            )
            if not cached:
                uncached_count += 1
            display = ("✓ " if cached else "  ") + rel
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, s3_prefix)
            item.setData(Qt.UserRole + 1, str(local_path))
            item.setData(Qt.UserRole + 2, cached)
            if cached:
                item.setForeground(QColor("#44CC44"))
            self._list.addItem(item)

        count = len(datasets)
        self._status_label.setText(
            f"{count} dataset{'s' if count != 1 else ''} found."
            if count
            else "No datasets found in the configured S3 location."
        )
        self._download_all_btn.setEnabled(uncached_count > 0)

    def _on_list_error(self, msg: str) -> None:
        if not self._closing:
            self._status_label.setText(f"Error listing datasets: {msg}")

    # ------------------------------------------------------------------
    # Selection handling
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        items = self._list.selectedItems()
        if not items:
            self._open_btn.setEnabled(False)
            self._open_btn.setText("Open →")
            self._redownload_btn.setEnabled(False)
            return

        cached_flags = [bool(item.data(Qt.UserRole + 2)) for item in items]
        all_cached = all(cached_flags)
        any_cached = any(cached_flags)

        if len(items) == 1:
            if all_cached:
                self._open_btn.setText("Open →")
                self._open_btn.setEnabled(True)
                self._redownload_btn.setEnabled(True)
            else:
                self._open_btn.setText("Download & Open")
                self._open_btn.setEnabled(True)
                self._redownload_btn.setEnabled(False)
        else:
            if all_cached:
                self._open_btn.setText("Open First →")
                self._open_btn.setEnabled(True)
                self._redownload_btn.setEnabled(True)
            else:
                self._open_btn.setText(f"Download Selected ({len(items)})")
                self._open_btn.setEnabled(True)
                self._redownload_btn.setEnabled(any_cached)

    # ------------------------------------------------------------------
    # Open / download
    # ------------------------------------------------------------------

    def _on_open_clicked(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return

        cached_flags = [bool(item.data(Qt.UserRole + 2)) for item in items]
        all_cached = all(cached_flags)

        if all_cached:
            # Open the first selected cached dataset.
            local_path = items[0].data(Qt.UserRole + 1)
            self.dataset_ready.emit(local_path)
            QTimer.singleShot(0, self.accept)
        else:
            # Download uncached items (and optionally force-re-download cached ones).
            uncached = [it for it in items if not it.data(Qt.UserRole + 2)]
            self._enqueue_and_start(uncached)

    def _on_redownload_clicked(self) -> None:
        items = self._list.selectedItems()
        if items:
            self._enqueue_and_start(items, force=True)

    def _on_download_all_clicked(self) -> None:
        all_items = [self._list.item(i) for i in range(self._list.count())]
        uncached = [it for it in all_items if it and not it.data(Qt.UserRole + 2)]
        if uncached:
            self._enqueue_and_start(uncached)

    # ------------------------------------------------------------------
    # Sequential download queue
    # ------------------------------------------------------------------

    def _enqueue_and_start(
        self, items: list[QListWidgetItem], force: bool = False
    ) -> None:
        queue = []
        for item in items:
            if force or not item.data(Qt.UserRole + 2):
                queue.append((item.data(Qt.UserRole), item.data(Qt.UserRole + 1)))
        if not queue:
            return

        self._download_queue = queue
        self._queue_done = 0
        self._queue_total = len(queue)
        self._cancelled = [False]

        self._open_btn.setEnabled(False)
        self._redownload_btn.setEnabled(False)
        self._download_all_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._cancel_btn.setText("Cancel Download")

        self._start_next_in_queue()

    def _start_next_in_queue(self) -> None:
        if not self._download_queue:
            return
        s3_prefix, local_path_str = self._download_queue.pop(0)
        local_path = Path(local_path_str)

        self._queue_done += 1
        self._status_label.setText(
            f"Downloading dataset {self._queue_done} / {self._queue_total}…"
        )
        self._progress_bar.setValue(0)

        worker = _DownloadWorker(
            self._client,
            self._config.s3_data_bucket,
            s3_prefix,
            local_path,
            self._cancelled,
        )
        thread = _make_thread(worker)
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(
            lambda lp=local_path_str: self._on_download_finished(lp)
        )
        worker.error.connect(self._on_download_error)
        thread.started.connect(worker.run)
        # Null out the reference once the thread finishes, but only if
        # self._download_thread still points to *this* thread.  In a chained
        # queue, _on_download_finished already replaced the reference with the
        # next thread before this lambda runs; the identity check prevents
        # wiping out that live reference and causing a GC-triggered crash.
        thread.finished.connect(
            lambda t=thread: (
                setattr(self, "_download_thread", None)
                if self._download_thread is t
                else None
            )
        )
        thread.start()
        self._download_thread = thread
        self._download_worker = worker

    def _on_download_progress(self, done: int, total: int) -> None:
        if self._closing:
            return
        if total > 0:
            self._progress_bar.setValue(int(done / total * 100))
        self._status_label.setText(
            f"Downloading dataset {self._queue_done} / {self._queue_total}"
            f"  —  {done} / {total} files"
        )

    def _on_download_finished(self, local_path_str: str) -> None:
        if self._closing:
            return

        self._progress_bar.setValue(100)

        # Mark the corresponding list item as cached.
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.UserRole + 1) == local_path_str:
                old_text = item.text().lstrip()
                item.setText("✓ " + old_text)
                item.setData(Qt.UserRole + 2, True)
                item.setForeground(QColor("#44CC44"))
                break

        if self._download_queue:
            self._start_next_in_queue()
        else:
            # All queued downloads finished.
            n = self._queue_total
            self._status_label.setText(
                f"All {n} dataset{'s' if n != 1 else ''} downloaded."
            )
            self._cancel_btn.setText("Cancel")
            self._progress_bar.setVisible(False)
            self._download_all_btn.setEnabled(False)
            # Re-evaluate button state based on current selection.
            self._on_selection_changed()

            # If it was a single-item download, auto-open.
            if n == 1:
                self.dataset_ready.emit(local_path_str)
                QTimer.singleShot(0, self.accept)

    def _on_download_error(self, msg: str) -> None:
        if self._closing:
            return
        self._download_queue.clear()
        self._status_label.setText(f"Download failed: {msg}")
        self._progress_bar.setVisible(False)
        self._cancel_btn.setText("Cancel")
        self._download_all_btn.setEnabled(True)
        self._on_selection_changed()

    def _on_cancel(self) -> None:
        if self._download_thread and self._download_thread.isRunning():
            self._cancelled[0] = True
            self._download_queue.clear()
            self._status_label.setText("Cancelling download…")
        else:
            self.reject()

    def _on_open_local(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select blocks directory", ".")
        if path:
            self.dataset_ready.emit(path)
            QTimer.singleShot(0, self.accept)

    # ------------------------------------------------------------------
    # Close — stop threads before dialog is destroyed
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._closing = True
        self._cancelled[0] = True
        self._download_queue.clear()

        for thread in (self._list_thread, self._download_thread):
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(5000)
            except RuntimeError:
                pass  # C++ object already deleted by deleteLater

        super().closeEvent(event)
