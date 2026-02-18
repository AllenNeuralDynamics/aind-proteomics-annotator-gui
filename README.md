# aind-proteomics-annotator-gui

A Python desktop GUI for annotating 3D multi-channel TIFF image blocks generated from proteomics imaging pipelines at the Allen Institute for Neural Dynamics (AIND). Multiple annotators on different machines access a shared filesystem simultaneously; the tool is designed to be safe under those conditions.

To execute `sh launch.sh`. You can change the configuration in the environment variables.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Data Format](#data-format)
- [Storage Format](#storage-format)
- [UI Walkthrough](#ui-walkthrough)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Admin Mode](#admin-mode)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Multi-Machine / NFS Safety](#multi-machine--nfs-safety)
- [Running Tests](#running-tests)
- [Development](#development)

---

## Overview

Annotators open the application, select a block from the sidebar, inspect its 3D multi-channel TIFF stack in an embedded napari viewer, and press **1**, **2**, or **3** to assign a class label. Annotations are saved immediately and atomically to a shared JSON file, visible to all other machines.

Admin users have a second tab that aggregates all user annotations, shows per-block majority-vote consensus, flags disagreements, allows label overrides, and exports the full dataset as a CSV.

---

## Key Features

| Feature | Detail |
|---|---|
| 3D napari viewer | Embedded inside a custom Qt window (not a napari plugin) |
| Multi-channel overlay | Channels stacked with additive blending |
| Per-channel controls | Independent LUT colour picker and dynamic range sliders |
| Z-slice auto-play | Cycles through slices at a configurable rate (default 2 s/frame) |
| Keyboard annotation | Press **1**, **2**, **3** to label the current block instantly |
| Auto-save | Every annotation is written to disk atomically before the next keystroke |
| Color-coded block list | Grey = unannotated, green/blue/orange = Class 1/2/3 |
| Admin panel | Consensus table, disagreement flags, label override, CSV export |
| NFS-safe storage | Atomic JSON writes (UUID temp + `os.replace` + `fsync`) |
| LRU block cache | Keeps the last N loaded blocks in memory (default 3) |
| Async loading | TIFF I/O runs in a background thread; UI never freezes |
| Env-var configuration | All paths overridable at runtime — same binary on any machine |

---

## Requirements

- Python ≥ 3.10
- A display (headless environments are not supported)
- Read/write access to a shared filesystem for annotation storage

### Python dependencies

| Package | Purpose |
|---|---|
| `napari[all]` | 3D image viewer (Qt backend included) |
| `tifffile` | Reading multi-dimensional TIFF stacks |
| `numpy` | Array operations |
| `superqt` | `QLabeledDoubleRangeSlider` for range controls |
| `qtpy` | Qt abstraction layer (PyQt5 / PySide6) |
| `vispy` | Low-level GPU rendering (pulled in by napari) |

---

## Installation

```bash
# Clone the repository
git clone https://github.com/AllenNeuralDynamics/aind-proteomics-annotator-gui.git
cd aind-proteomics-annotator-gui

# Create and activate a virtual environment (Python ≥ 3.10 required)
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install the package and all runtime dependencies
pip install -e .

# Optional: install development extras (pytest, ruff)
pip install -e ".[dev]"
```

---

## Configuration

All paths are controlled by environment variables so the same installation works on any machine regardless of where the shared filesystem is mounted.

| Variable | Default | Description |
|---|---|---|
| `ANNOTATOR_DATA_ROOT` | `./data/blocks` | Root directory that contains `block_xxxx/` sub-folders |
| `ANNOTATOR_ANNOTATIONS_ROOT` | `./annotations` | Root directory for annotation JSON files |
| `ANNOTATOR_ROLES_FILE` | `./configs/roles.json` | Path to the admin roles definition file |

### Admin users — `configs/roles.json`

```json
{
  "admins": ["alice", "bob_admin"]
}
```

Any username listed under `"admins"` will see the **Admin View** tab at login. Edit this file to add or remove admin users. The file is read at startup; changes take effect on the next launch.

### Recommended NFS mount options (shared filesystem)

For best reliability on NFS mounts, disable attribute caching on the annotations directory:

```
noac,sync,lookupcache=none
```

This is optional — the atomic write strategy works without it, but these options eliminate the small window where a remote client may read a stale dentry.

---

## Running the Application

```bash
# With environment variables pointing to a shared mount
export ANNOTATOR_DATA_ROOT=/mnt/shared/proteomics/data/blocks
export ANNOTATOR_ANNOTATIONS_ROOT=/mnt/shared/proteomics/annotations
export ANNOTATOR_ROLES_FILE=/mnt/shared/proteomics/configs/roles.json

proteomics-annotator
# or equivalently:
python -m aind_proteomics_annotator
```

On first launch a login dialog prompts for a username. The username must contain only letters, digits, or underscores. It is stored in lowercase.

---

## Data Format

```
data/
└── blocks/
    ├── block_0001/
    │   ├── channel_0.tiff    # Shape: (Z=128, Y=128, X=128), dtype uint16
    │   ├── channel_1.tiff
    │   └── channel_2.tiff
    ├── block_0002/
    │   └── ...
    └── block_NNNN/
```

- Block folder names must match the pattern `block_NNNN` (4 decimal digits).
- Each `.tiff` / `.tif` file inside a block folder is treated as one channel.
- Files are loaded in lexicographic order (channel_0 first).
- Expected volume shape: **(Z, Y, X) = (128, 128, 128)** per channel.
- Any number of channels per block is supported.

---

## Storage Format

All annotation data is plain JSON. No database is required.

### Per-user annotations — `annotations/users/{username}.json`

```json
{
  "username": "alice",
  "created_at": "2024-01-01T00:00:00+00:00",
  "updated_at": "2024-01-02T10:30:00+00:00",
  "annotations": {
    "block_0001": {
      "label": 1,
      "annotated_at": "2024-01-02T10:30:00+00:00"
    },
    "block_0002": {
      "label": 3,
      "annotated_at": "2024-01-02T11:00:00+00:00"
    }
  }
}
```

Each annotator has their own file. Files are never shared between users, which eliminates write conflicts entirely.

### Admin final labels — `annotations/admin/final_labels.json`

```json
{
  "updated_at": "2024-01-02T12:00:00+00:00",
  "labels": {
    "block_0001": {
      "final_label": 1,
      "set_by": "alice",
      "set_at": "2024-01-02T12:00:00+00:00"
    }
  }
}
```

Written only by admin users via the **Override Final Label** control in the Admin View tab.

---

## UI Walkthrough

```
┌─────────────────────────────────────────────────────────────────┐
│  Title bar: "Proteomics Annotator — {username}"                 │
├──────────────┬──────────────────────────────────────────────────┤
│              │  [ Annotator ] [ Admin View ]  (admin only)      │
│  block_0001  │  ┌─────────────────────────┬────────────────┐   │
│  block_0002  │  │                         │  Channel 0     │   │
│  block_0003  │  │    napari 3D viewer     │  LUT: [■■■■]   │   │
│  block_0004  │  │                         │  Range: ──●─●  │   │
│     ...      │  │  ┌─── overlay ───┐      │                │   │
│              │  │  │Label: 1 — C1  │      │  Channel 1     │   │
│              │  │  └───────────────┘      │  LUT: [■■■■]   │   │
│              │  │                         │  Range: ──●─●  │   │
│  42/100      │  └─────────────────────────┴────────────────┘   │
│  annotated   │  Z-slice auto-play:  [ Start ]  (2s/frame)       │
├──────────────┴──────────────────────────────────────────────────┤
│  Block: block_0042  |  Press 1, 2, 3 to annotate  [████░░] 42/100│
└─────────────────────────────────────────────────────────────────┘
```

### Left sidebar — Block List

- Lists every `block_NNNN` folder found under `ANNOTATOR_DATA_ROOT`.
- Click a block to load it into the viewer.
- Color of each item indicates its annotation status:
  - **Grey** — not yet annotated
  - **Green** — Class 1
  - **Blue** — Class 2
  - **Orange** — Class 3
- Counter at the bottom shows `{annotated} / {total} annotated`.

### Main panel — napari viewer

- All channels are loaded simultaneously and stacked with **additive blending**.
- The napari dimension slider at the bottom controls the active Z-slice.
- The viewer is embedded headlessly — napari's own window is never shown.

### Right panel — Channel Controls

- One collapsible group per channel, populated after each block load.
- **Pick Color** opens a colour dialog and updates the channel's LUT via a vispy `Colormap(["black", chosen_colour])`.
- **Range slider** (`superqt.QLabeledDoubleRangeSlider`) adjusts `contrast_limits` on the napari layer in real time.

### Top-left overlay

- Shows the current annotation label and class name for the visible block.
- Colour matches the label: green = 1, blue = 2, orange = 3, grey = unlabelled.
- In admin mode the overlay also shows the consensus label and agree/disagree status.

### Bottom bar

- Displays the active block name and a reminder of the keyboard shortcuts.
- Shows a "Loading…" indicator during async TIFF loads.
- Progress bar tracks total annotation completion.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| **1** | Assign Class 1 to the current block |
| **2** | Assign Class 2 to the current block |
| **3** | Assign Class 3 to the current block |

Shortcuts use `Qt.ApplicationShortcut` context, so they fire even when the napari canvas holds keyboard focus. Annotation is saved to disk atomically before the next key event is processed.

---

## Admin Mode

Users listed in `configs/roles.json` → `"admins"` see a second **Admin View** tab.

### Consensus table

| Column | Description |
|---|---|
| Block ID | `block_NNNN` identifier |
| Consensus | Majority-vote label across all annotators |
| Final Label | Admin override (amber background if set) |
| Status | Colour-coded: grey = unannotated, dark green = agree, red = disagree |
| `{username}` ... | One column per annotator showing their individual label |

### Consensus algorithm

1. Collect all non-null labels for the block.
2. Count votes with `collections.Counter`.
3. The label with the highest vote count wins.
4. **Tie-breaking**: if multiple labels share the highest count, the numerically smallest label is chosen.
5. `has_disagreement = True` whenever more than one distinct label was submitted.

### Override final label

1. Click any row in the table to select a block.
2. Use the spin box to choose a label (1–3).
3. Click **Set Final Label** — writes to `annotations/admin/final_labels.json` atomically.
4. The table refreshes automatically.

### Export CSV

Click **Export CSV…** to save a CSV file with these columns:

```
block_id, consensus_label, final_label, has_disagreement,
user_{username}_label (one per annotator, sorted),
exported_at
```

### Statistics box

Shows live counts for:
- Total blocks
- Blocks annotated by at least one user
- Blocks with disagreement
- Consensus rate (% of annotated blocks where all annotators agree)
- Number of annotators who have submitted at least one label

---

## Project Structure

```
aind-proteomics-annotator-gui/
│
├── pyproject.toml                      # Package metadata + dependencies
├── .gitignore
├── LICENSE                             # MIT
├── README.md
│
├── configs/
│   └── roles.json                      # Admin username list (commit this)
│
├── data/                               # Gitignored — mount-point for block TIFFs
│   └── blocks/
│       └── block_NNNN/
│           ├── channel_0.tiff
│           └── channel_1.tiff
│
├── annotations/                        # Gitignored — mount-point for annotation JSON
│   ├── users/
│   │   └── {username}.json
│   └── admin/
│       └── final_labels.json
│
├── src/
│   └── aind_proteomics_annotator/
│       ├── __init__.py
│       ├── __main__.py                 # Entry point: QApplication + LoginDialog + MainWindow
│       ├── config.py                   # AppConfig dataclass (env-var paths + tunable defaults)
│       │
│       ├── models/                     # Pure-Python data layer (no Qt)
│       │   ├── annotation_store.py     # AnnotationStore + FinalLabelStore (JSON CRUD)
│       │   ├── block_registry.py       # Filesystem scan → list[BlockInfo]
│       │   └── user_session.py         # Active user: store + is_admin flag
│       │
│       ├── workers/
│       │   └── tiff_loader.py          # @thread_worker + BlockCache (LRU)
│       │
│       ├── gui/
│       │   ├── main_window.py          # QMainWindow: layout assembly + keyboard shortcuts
│       │   ├── login_dialog.py         # Username prompt dialog
│       │   ├── block_list_panel.py     # Left sidebar (color-coded QListWidget)
│       │   ├── viewer_panel.py         # napari viewer embed + Z-slice autoplay
│       │   ├── channel_controls.py     # Per-channel LUT + range sliders
│       │   ├── bottom_panel.py         # Progress bar + status label
│       │   ├── overlay_widget.py       # Semi-transparent top-left QLabel
│       │   └── admin_panel.py          # Admin review tab
│       │
│       └── utils/
│           ├── atomic_io.py            # atomic_write_json + read_json (NFS-safe)
│           ├── consensus.py            # Majority vote + build_consensus_table
│           └── csv_exporter.py         # export_csv → CSV file
│
└── tests/
    ├── conftest.py                     # Shared fixtures
    ├── test_atomic_io.py               # 6 tests for atomic I/O
    ├── test_annotation_store.py        # 11 tests for AnnotationStore + FinalLabelStore
    ├── test_block_registry.py          # 7 tests for BlockRegistry
    └── test_consensus.py               # 12 tests for compute_consensus + build_consensus_table
```

---

## Architecture

### Startup sequence

```
python -m aind_proteomics_annotator
    │
    ├─ QApplication (must exist before any Qt widget or napari import)
    ├─ AppConfig.from_environment()        read env vars → paths + defaults
    ├─ LoginDialog.exec()                  blocking modal; exits on cancel
    ├─ UserSession.load_or_create()
    │       ├─ mkdir annotations/users/ + admin/
    │       ├─ AnnotationStore.load_or_create()   create {username}.json if absent
    │       ├─ FinalLabelStore.load()
    │       └─ read roles.json → set is_admin
    ├─ BlockRegistry.scan()               glob data_root for block_NNNN dirs
    ├─ MainWindow(session, config, registry)
    │       ├─ BlockListPanel.populate()
    │       ├─ napari.Viewer(show=False)   headless viewer
    │       ├─ embed viewer.window._qt_viewer into ViewerPanel layout
    │       ├─ QShortcut(1/2/3) with Qt.ApplicationShortcut
    │       └─ AdminPanel (if is_admin)
    ├─ MainWindow.show()
    └─ app.exec()                          Qt event loop
```

### Annotation flow (normal user)

```
Click block in sidebar
    → BlockListPanel.block_selected(block_id)
    → MainWindow._on_block_selected(block_id)
    → ViewerPanel.load_block(block_info)
        → loading_started signal → BottomPanel shows "Loading…"
        → load_block_worker started in background QThread
            → BlockCache hit? return cached arrays
            → tifffile.imread × N channels → float32 arrays
            → return (block_id, arrays)
        → worker.returned signal (main thread)
        → viewer.layers.clear()
        → viewer.add_image(arr, colormap=..., blending="additive") × N
        → channels_loaded signal → ChannelControlsPanel.setup_channels()
        → restore label overlay from AnnotationStore
        → loading_finished signal → BottomPanel hides "Loading…"

Press key "2"
    → QShortcut.activated → MainWindow._annotate(label=2)
    → AnnotationStore.set_label(block_id, 2)
        → atomic_write_json(users/alice.json, updated_data)
    → ViewerPanel.show_label(2, "Class 2")
        → OverlayWidget.set_label(2, "Class 2")
    → BlockListPanel.refresh_block_status(block_id)
        → item foreground → blue
    → BottomPanel.update_progress(annotated_count)
```

### napari embedding

napari is embedded headlessly into the custom `QMainWindow`, rather than running as a standalone application:

```python
# In ViewerPanel.__init__:
import napari, warnings

self._viewer = napari.Viewer(show=False)          # 1. create model + Qt infra, no window shown

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    qt_viewer_widget = self._viewer.window._qt_viewer   # 2. grab the QSplitter widget
                                                          #    (canvas + dim sliders)

layout.addWidget(qt_viewer_widget)                # 3. Qt reparents it into our layout
```

All napari layer operations (`viewer.add_image`, `viewer.layers.clear`, etc.) work normally — they operate on the model, and the embedded `QtViewer` renders them inside our window.

**Why `_qt_viewer` and not a plugin?** Using the `_qt_viewer` approach gives full control over the outer window layout (sidebar, tabs, bottom bar). A napari plugin/dockwidget approach would be cleaner in future but would force us to live inside napari's own window structure.

> **Note**: `_qt_viewer` carries a `FutureWarning` in napari < 0.6.0 (it is a semi-private attribute). The warning is suppressed at the call site. If napari ≥ 0.6.0 changes the API, replace the access with the public equivalent documented in that release.

### Async TIFF loading

TIFF files are loaded off the main thread using napari's `@thread_worker` decorator, which wraps a regular Python function in a `QThread` and communicates back via Qt signals:

```python
@thread_worker
def load_block_worker(tiff_paths, block_id, cache):
    cached = cache.get(block_id)
    if cached:
        return block_id, cached
    arrays = [tifffile.imread(p).astype(np.float32) for p in tiff_paths]
    cache.put(block_id, arrays)
    return block_id, arrays

# Usage (main thread):
worker = load_block_worker(paths, block_id, cache)
worker.returned.connect(self._on_block_loaded)   # runs in main thread via Qt signal
worker.start()
```

`viewer.add_image()` is always called inside `_on_block_loaded`, which runs in the main thread via the Qt signal dispatch — never from the background thread.

The `BlockCache` is an `OrderedDict`-backed LRU cache (capacity configurable via `AppConfig.max_cached_blocks`, default 3). It is accessed only from the main thread so no locking is required.

---

## Multi-Machine / NFS Safety

Each annotator writes only their own `users/{username}.json` file. These are independent files, so concurrent writes from multiple machines **never target the same file** under normal operation. The only shared write target is `admin/final_labels.json`, which is written exclusively by admin users.

### Atomic write strategy (`utils/atomic_io.py`)

Every JSON write follows this sequence:

```
1.  tmp = same_dir / f".{stem}_{uuid4().hex}.tmp"   # unique name per write
2.  write JSON → tmp_file
3.  fh.flush() + os.fsync(fh.fileno())              # data → NFS server
4.  os.replace(tmp, target)                          # POSIX atomic rename
5.  os.fsync(dir_fd)                                 # rename → NFS server
```

- **No partial reads**: readers always see either the old complete file or the new complete file — never a partially written version.
- **No collision**: the UUID suffix means two concurrent writers targeting the same file produce different temp names. The last `os.replace` wins atomically.
- **NFS durability**: both `fsync` calls ensure data is on the server before the rename, and the directory `fsync` ensures the rename itself is durable.

### Read retry loop

`read_json` retries up to 3 times with exponential backoff (50 ms, 100 ms) on `OSError` or `JSONDecodeError`. This handles the brief window where a remote NFS client has a stale dentry cache entry pointing to a file in mid-rename.

### Why no file locks?

NFS advisory locks (`fcntl.flock`) are unreliable across different kernel versions and NFS client/server configurations. Since each user owns a separate file, locks are unnecessary for the common case. Admin override writes are infrequent single-operator operations that are safe without locking.

---

## Running Tests

```bash
# Activate a Python ≥ 3.10 environment with pytest installed
source .venv/bin/activate

# Run all pure-Python tests (no display required)
PYTHONPATH=src pytest tests/ -v

# Run with coverage
PYTHONPATH=src pytest tests/ --cov=aind_proteomics_annotator --cov-report=term-missing
```

The tests cover:
- `test_atomic_io.py` — round-trip, parent dir creation, no temp file leaks, overwrite, retry
- `test_annotation_store.py` — CRUD, persistence across instances, overwrite
- `test_block_registry.py` — discovery, sorting, filtering, channel count
- `test_consensus.py` — unanimous, majority, ties, None handling, multi-block tables

GUI tests (Qt/napari) require a display and are not included in the default suite. Add `pytest-qt` for those.

---

## Development

```bash
# Lint with ruff
ruff check src/ tests/

# Format
ruff format src/ tests/

# Install pre-commit hooks (optional)
pip install pre-commit
pre-commit install
```

### Adding a new annotation class

1. Edit `configs/roles.json` — no code change needed.
2. Update `AppConfig.classes` in [src/aind_proteomics_annotator/config.py](src/aind_proteomics_annotator/config.py) to add the new class name.
3. The keyboard shortcuts in `MainWindow._install_shortcuts` are generated dynamically from `config.classes`, so a fourth class automatically binds to key **4**.
4. Update `_LABEL_COLORS` in [overlay_widget.py](src/aind_proteomics_annotator/gui/overlay_widget.py) and [block_list_panel.py](src/aind_proteomics_annotator/gui/block_list_panel.py) to add a colour for the new label.

### Environment variable reference (full)

| Variable | Default | Notes |
|---|---|---|
| `ANNOTATOR_DATA_ROOT` | `./data/blocks` | Contains `block_NNNN/` sub-dirs |
| `ANNOTATOR_ANNOTATIONS_ROOT` | `./annotations` | Contains `users/` and `admin/` |
| `ANNOTATOR_ROLES_FILE` | `./configs/roles.json` | Admin username list |
| `QT_API` | (auto) | Force Qt binding: `pyqt5`, `pyside6`, etc. |

---

## License

MIT — see [LICENSE](LICENSE).
