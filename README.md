# aind-proteomics-annotator-gui

A Python desktop GUI for annotating 3D multi-channel TIFF image blocks generated from proteomics imaging pipelines at the Allen Institute for Neural Dynamics (AIND). Multiple annotators on different machines access a shared filesystem simultaneously; the tool is designed to be safe under those conditions.

To execute: `sh launch.sh`. All paths and S3 settings are controlled by environment variables.

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
- [S3 Integration](#s3-integration)
  - [AWS SSO setup](#aws-sso-setup-recommended-for-aind)
  - [Re-authenticating after token expiry](#re-authenticating-after-token-expiry)
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

When S3 is configured, annotators can browse and download datasets directly from S3. Annotations for cloud-sourced datasets are automatically uploaded back to S3 on dataset switch and on app close.

Admin users have a second tab that aggregates all user annotations, shows per-block majority-vote consensus, flags disagreements, allows label overrides, and exports the full dataset as a CSV.

---

## Key Features

| Feature | Detail |
|---|---|
| 3D napari viewer | Embedded inside a custom Qt window (not a napari plugin) |
| Multi-channel overlay | Channels stacked with additive blending |
| Per-channel controls | Independent LUT colour picker and dynamic range sliders |
| Global display preferences | Channel intensity/LUT settings apply to all datasets and persist across sessions |
| Z-slice auto-play | Cycles through slices at a configurable rate (default 100 ms/frame) |
| Keyboard annotation | Press **1**, **2**, **3** (…N) to label the current block instantly |
| Auto-save | Every annotation is written to disk atomically before the next keystroke |
| Auto-advance to next dataset | When all blocks in a dataset are annotated, automatically opens the next unannotated dataset |
| Color-coded block list | Grey = unannotated; configurable colors per class |
| Dataset browser | Sidebar lists all discoverable datasets with per-dataset annotation progress |
| S3 dataset browser | Browse, multi-select, and batch-download datasets from S3 |
| S3 annotation upload | Cloud-sourced annotations are uploaded to S3 automatically (date-stamped, non-destructive) |
| Admin panel | Consensus table, disagreement flags, label override, CSV export; Local/Cloud source toggle |
| NFS-safe storage | Atomic JSON writes (UUID temp + `os.replace` + `fsync`) |
| LRU block cache | Keeps the last N loaded blocks in memory (default 10) |
| Async loading | TIFF I/O runs in a background thread; UI never freezes |
| Env-var configuration | All paths overridable at runtime — same binary on any machine |

---

## Requirements

- Python ≥ 3.10
- A display (headless environments are not supported)
- Read/write access to a shared filesystem for annotation storage
- *(Optional)* AWS credentials for S3 integration

### Python dependencies

| Package | Purpose |
|---|---|
| `napari[all]` | 3D image viewer (Qt backend included) |
| `tifffile` | Reading multi-dimensional TIFF stacks |
| `numpy` | Array operations |
| `superqt` | `QLabeledDoubleRangeSlider` for range controls |
| `qtpy` | Qt abstraction layer (PyQt5 / PySide6) |
| `vispy` | Low-level GPU rendering (pulled in by napari) |
| `boto3` *(optional)* | AWS SDK — required only for S3 integration |

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

# Optional: S3 support
pip install boto3

# Optional: install development extras (pytest, ruff)
pip install -e ".[dev]"
```

---

## Configuration

All paths and S3 settings are controlled by environment variables.

### Core variables

| Variable | Default | Description |
|---|---|---|
| `ANNOTATOR_DATA_ROOT` | `./data/blocks` | Root directory containing `block_NNNN/` or `block_UUID/` sub-folders |
| `ANNOTATOR_ANNOTATIONS_ROOT` | `./annotations` | Root directory for all annotation JSON files |
| `ANNOTATOR_ROLES_FILE` | `./configs/roles.json` | Path to the admin roles definition file |
| `ANNOTATOR_CLASSES_FILE` | `./configs/classes.json` | Path to class and channel name definitions |

### S3 variables *(all optional)*

| Variable | Default | Description |
|---|---|---|
| `ANNOTATOR_S3_DATA_BUCKET` | *(disabled)* | Source S3 bucket containing datasets to download and annotate |
| `ANNOTATOR_S3_DATA_PREFIX` | `""` | Key prefix within the data bucket (e.g. `experiments/2025`) |
| `ANNOTATOR_S3_OUTPUT_BUCKET` | *(disabled)* | S3 bucket where annotation JSONs are uploaded |
| `ANNOTATOR_S3_OUTPUT_PREFIX` | `annotations` | Key prefix for annotation uploads |
| `ANNOTATOR_S3_PROFILE` | *(default)* | AWS credentials profile name (from `~/.aws/credentials`) |
| `ANNOTATOR_S3_LOCAL_CACHE` | *(auto-detected)* | Local directory for downloaded datasets. If unset, the app walks up from `ANNOTATOR_DATA_ROOT` to find the experiment root (the ancestor that contains `Tile_*` siblings) and places `cloud_datasets/` there. |

Setting either `ANNOTATOR_S3_DATA_BUCKET` or `ANNOTATOR_S3_OUTPUT_BUCKET` activates S3 features. You can set just one (e.g. output-only or download-only).

### Class definitions — `configs/classes.json`

```json
{
  "classes": [
    {"name": "Class 1", "color": "#22AA44"},
    {"name": "Class 2", "color": "#2266FF"},
    {"name": "Class 3", "color": "#FF6622"}
  ],
  "channel_names": ["DAPI", "NeuN", "GFAP"]
}
```

Keys **1**…**N** are bound automatically from this list. `channel_names` labels the channel controls panel; if omitted, channels are named "Channel 0", "Channel 1", etc.

### Admin users — `configs/roles.json`

```json
{
  "admins": ["alice", "bob_admin"]
}
```

Any username listed under `"admins"` will see the **Admin View** tab. Edit this file to add or remove admin users; changes take effect on the next launch.

### Recommended NFS mount options (shared filesystem)

```
noac,sync,lookupcache=none
```

This is optional — the atomic write strategy works without it, but these options eliminate the small window where a remote client may read a stale dentry.

---

## Running the Application

```bash
# Local-only mode (no S3)
export ANNOTATOR_DATA_ROOT=/mnt/shared/proteomics/data/Tile_X_0001_Y_0003/ch_561/blocks
export ANNOTATOR_ANNOTATIONS_ROOT=/mnt/shared/proteomics/annotations
export ANNOTATOR_ROLES_FILE=/mnt/shared/proteomics/configs/roles.json

proteomics-annotator
# or equivalently:
python -m aind_proteomics_annotator
```

```bash
# With S3 integration
export ANNOTATOR_DATA_ROOT=/local/data/Tile_X_0001/ch_561/blocks
export ANNOTATOR_ANNOTATIONS_ROOT=/local/annotations
export ANNOTATOR_S3_DATA_BUCKET=my-proteomics-bucket
export ANNOTATOR_S3_DATA_PREFIX=experiments/HCR_2025
export ANNOTATOR_S3_OUTPUT_BUCKET=my-proteomics-annotations

proteomics-annotator
```

On first launch a **login dialog** prompts for a username (letters, digits, underscores only; stored lowercase). The dialog also shows the current S3 credential status so you can diagnose connection issues before entering the app.

---

## Data Format

```
data/
├── Tile_X_0001_Y_0003_Z_0000/
│   └── ch_561/
│       └── blocks/                   ← ANNOTATOR_DATA_ROOT points here
│           ├── block_0001/
│           │   ├── channel_0.tiff    # Shape: (Z=128, Y=128, X=128), dtype uint16
│           │   ├── channel_1.tiff
│           │   └── channel_2.tiff
│           ├── block_0002/
│           └── block_3f8a…/          # UUID-named blocks also supported
│
└── cloud_datasets/                   ← S3 downloads land here (auto-created)
    └── HCR_000000-s107-ls1_2026-01-23/
        └── Tile_X_0000_Y_0000_Z_0000/
            └── ch_561/
                └── blocks/
                    └── block_0001/
```

- Block folder names must match `block_NNNN` (4 decimal digits) **or** `block_<UUID>`.
- Each `.tiff` / `.tif` file inside a block folder is treated as one channel.
- Files are loaded in lexicographic order.
- Expected volume shape: **(Z, Y, X)** per channel.
- Any number of channels per block is supported.

---

## Storage Format

All annotation data is plain JSON. No database is required.

```
annotations/
├── users/
│   ├── local/
│   │   └── {username}/
│   │       └── {experiment}/
│   │           └── {tile}_{ch}_blocks.json   ← one file per dataset, local
│   ├── cloud/
│   │   └── {username}/
│   │       └── {experiment}/
│   │           └── {tile}_{ch}_blocks.json   ← one file per dataset, cloud
│   └── display_preferences/
│       └── {username}.json                   ← global channel LUT/intensity settings
└── admin/
    ├── local/
    │   └── {dataset_slug}_final_labels.json  ← admin overrides for local datasets
    └── cloud/
        └── {dataset_slug}_final_labels.json  ← admin overrides for cloud datasets
```

Annotation files are **scoped per dataset** — one JSON file per (user, dataset) pair. The path is derived from the dataset key: the first path component becomes a sub-directory (experiment name) and the rest is flattened into the filename. For example, dataset key `HCR_000000-s107-ls1_2026-01-23_00-00-00/Tile_X_0000_Y_0000_Z_0000/ch_561/blocks` maps to `{username}/HCR_000000-s107-ls1_2026-01-23_00-00-00/Tile_X_0000_Y_0000_Z_0000_ch_561_blocks.json`.

Local and cloud annotations are stored under separate trees so cloud annotations can be uploaded to S3 independently.

### Per-user annotations — `annotations/users/{local|cloud}/{username}/{experiment}/{slug}.json`

```json
{
  "username": "alice",
  "dataset_key": "HCR_000000-s107-ls1_2026-01-23_00-00-00/Tile_X_0000_Y_0000_Z_0000/ch_561/blocks",
  "dataset_slug": "HCR_000000-s107-ls1_2026-01-23_00-00-00_Tile_X_0000_Y_0000_Z_0000_ch_561_blocks",
  "created_at": "2024-01-01T00:00:00+00:00",
  "updated_at": "2024-01-02T10:30:00+00:00",
  "annotations": {
    "block_0001": {"label": 1, "annotated_at": "2024-01-02T10:30:00+00:00"},
    "block_0002": {"label": 3, "annotated_at": "2024-01-02T11:00:00+00:00"}
  }
}
```

### Display preferences — `annotations/users/display_preferences/{username}.json`

Stores per-channel LUT color and contrast range. Settings are **global** — they apply to all datasets and persist across dataset switches. Written and read by the channel controls panel.

### Admin final labels — `annotations/admin/{local|cloud}/final_labels.json`

```json
{
  "updated_at": "2024-01-02T12:00:00+00:00",
  "labels": {
    "/absolute/path/to/blocks": {
      "block_0001": {
        "final_label": 1,
        "set_by": "alice",
        "set_at": "2024-01-02T12:00:00+00:00"
      }
    }
  }
}
```

Written only by admin users. The admin panel has a **Local / Cloud** toggle to work with either store independently.

---

## S3 Integration

S3 features are activated by setting `ANNOTATOR_S3_DATA_BUCKET` and/or `ANNOTATOR_S3_OUTPUT_BUCKET`. The login dialog reports credential status at startup.

### Downloading datasets

1. Click the **S3…** button in the sidebar (active when credentials are available).
2. The dialog lists all `blocks/` prefixes found under the configured bucket/prefix.
   - Green rows with a ✓ are already cached locally.
   - White rows are not yet downloaded.
3. **Single dataset**: click a row → "Open →" (cached) or "Download & Open" (uncached).
4. **Multiple datasets**: Ctrl+click or Shift+click to select several rows → "Download Selected (N)".
5. **All uncached**: click **Download All** to queue every uncached dataset.

Downloads are sequential; a progress bar and `"Dataset M / N"` counter show queue progress. The dialog stays open after a batch download so you can choose which dataset to open.

Downloaded datasets are cached locally under `cloud_datasets/` (see `ANNOTATOR_S3_LOCAL_CACHE`).

### Uploading annotations

Annotations for cloud-sourced datasets (those under `cloud_datasets/`) are uploaded automatically:

- When you switch to a different dataset.
- When the application closes.

Uploads go to:
```
s3://{ANNOTATOR_S3_OUTPUT_BUCKET}/{ANNOTATOR_S3_OUTPUT_PREFIX}/users/{username}/{dataset_slug}/{YYYY-MM-DD}.json
```

A new date-stamped file is created each day — existing files are never overwritten. Local annotations are **never** uploaded.

Admin final-label uploads (triggered when the admin clicks **Set Final Label** in Cloud mode) go to:
```
s3://{ANNOTATOR_S3_OUTPUT_BUCKET}/{ANNOTATOR_S3_OUTPUT_PREFIX}/admin/{experiment}/{tile}_{ch}_blocks_{YYYY-MM-DD}_final_labels.json
```

### AWS credentials

The standard credential chain is checked silently at startup (env vars → `~/.aws/credentials` → instance profile). No interactive credential dialog is shown.

#### AWS SSO setup (recommended for AIND)

AIND machines use AWS IAM Identity Center (SSO). Follow these steps once per machine:

**1. Install the AWS CLI v2**

```bash
# macOS (Homebrew)
brew install awscli

# Linux — see https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
```

**2. Configure an SSO profile**

```bash
aws configure sso
```

Follow the prompts:

| Prompt | Example value |
|---|---|
| SSO session name | `aind-sso` |
| SSO start URL | `https://your-org.awsapps.com/start` |
| SSO region | `us-west-2` |
| Default output format | `json` |

At the end of the wizard AWS will ask you to name the profile (e.g. `aind`). Use that name for `ANNOTATOR_S3_PROFILE`:

For AIND users, follow Yosef Bedaso's email related to SSO authentication to configure the console.

```bash
export ANNOTATOR_S3_PROFILE=your-profile
```

**3. Log in for the first time**

```bash
aws sso login --profile your-profile
```

This opens a browser tab where you approve the request. On success the tool can access S3 immediately.

#### Re-authenticating after token expiry

SSO tokens expire (typically after 8–12 hours or when your session ends). When credentials expire you will see an error dialog inside the app:

> *AWS credentials have expired. Run the following command in your terminal, then click S3 again:*
> `aws sso login --profile your-profile`

**To re-authenticate without restarting the app:**

1. Open a terminal (keep the app running).
2. Run:
   ```bash
   aws sso login --profile your-profile
   ```
3. Approve the browser prompt.
4. Back in the app, click the **S3…** button (or retry the failing action) — the app picks up the refreshed token automatically without restarting.

---

The login will tell you if AWS credentials were accepted or not.

If you're using the launch.sh script, you can set the environment variables there:

S3 config:
> export ANNOTATOR_S3_DATA_BUCKET=some-bucket
> export ANNOTATOR_S3_DATA_PREFIX=some-prefix
> export ANNOTATOR_S3_OUTPUT_BUCKET=some-output-bucket
> export ANNOTATOR_S3_OUTPUT_PREFIX=some-output-prefix
> export ANNOTATOR_S3_PROFILE=some-profile

- ANNOTATOR_S3_DATA_BUCKET: Bucket where the annotation blocks are stored.
- ANNOTATOR_S3_DATA_PREFIX: Prefix where the annotation blocks are stored.
- ANNOTATOR_S3_OUTPUT_BUCKET: Output bucket for the generated annotations.
- ANNOTATOR_S3_OUTPUT_PREFIX: Prefix for the generated annotations.
- ANNOTATOR_S3_PROFILE: your-profile. This needs to have the required permissions to write to the previously given bucket.

## UI Walkthrough

```
┌─────────────────────────────────────────────────────────────────────┐
│  Title: "Proteomics Annotator — {username}  |  {dataset}"           │
├──────────────────┬──────────────────────────────────────────────────┤
│ [Browse…] [S3…]  │  [ Annotator ] [ Admin View ]  (admin only)      │
│                  │  ┌─────────────────────────┬────────────────┐   │
│ Datasets         │  │                         │  Channel 0     │   │
│ ✓ ch_561  4/4    │  │    napari 3D viewer     │  LUT: [■■■■]   │   │
│   ch_488  2/4    │  │                         │  Range: ──●─●  │   │
│                  │  │  ┌─── overlay ───┐      │                │   │
│ ch_561           │  │  │ Label: 1 — C1 │      │  Channel 1     │   │
│                  │  │  └───────────────┘      │  LUT: [■■■■]   │   │
│ block_0001  ✓    │  │                         │  Range: ──●─●  │   │
│ block_0002  ✓    │  └─────────────────────────┴────────────────┘   │
│ block_0003       │                                                   │
│ block_0004       │                                                   │
│                  │                                                   │
│ 2 / 4 annotated  │                                                   │
│ ☑ Auto-advance   │                                                   │
│ ☐ Skip annotated │                                                   │
├──────────────────┴──────────────────────────────────────────────────┤
│  Block: block_0003  |  Press 1, 2, 3 to annotate      [████░░] 2/4 │
└─────────────────────────────────────────────────────────────────────┘
```

### Left sidebar — Block List

- **Browse…** — opens a folder dialog to switch to a local `blocks/` directory.
- **S3…** — opens the S3 dataset browser (enabled when credentials are configured).
- **Datasets** — lists all `blocks/` directories discovered near `ANNOTATOR_DATA_ROOT`, color-coded:
  - Green — fully annotated
  - Orange — partially annotated
  - Grey — not started
  Click any row to switch to that dataset.
- **Block list** — all blocks in the current dataset, color-coded by annotation status. Auto-advances to the next unannotated dataset when all blocks are labeled.
- **Auto-advance** — move to the next block automatically after labeling.
- **Skip annotated** — navigation skips already-labeled blocks.

### Main panel — napari viewer

- All channels loaded simultaneously with **additive blending**.
- The napari dimension slider controls the active Z-slice.
- The viewer is embedded headlessly inside the custom `QMainWindow`.

### Right panel — Channel Controls

- One collapsible group per channel.
- **Pick Color** opens a colour dialog; updates the channel LUT in real time.
- **Range slider** adjusts `contrast_limits` on the napari layer in real time.
- Settings are saved globally (not per dataset) and restored on the next launch.

### Top-left overlay

- Shows the current annotation label and class name.
- Colour matches the configured class color.
- In admin mode also shows the consensus label and agree/disagree status.

### Bottom bar

- Active block name and keyboard shortcut reminder.
- "Loading…" indicator during async TIFF loads.
- "Uploading annotations to S3…" indicator during S3 uploads.
- Progress bar showing total annotation completion for the current dataset.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| **1** … **N** | Assign Class N to the current block |
| **Space** | Toggle Z-slice auto-play |
| **↑ / ↓** | Previous / next block |
| **R** | Reset napari view |
| **Backspace** | Undo current block annotation |
| **Alt+1** … **Alt+7** | Toggle visibility of channel 1–7 |

All shortcuts use `Qt.ApplicationShortcut` context, so they fire even when the napari canvas holds keyboard focus.

---

## Admin Mode

Users listed in `configs/roles.json` → `"admins"` see an **Admin View** tab. The admin panel has a **Local / Cloud** source toggle — Local reads from `annotations/users/local/` and `admin/local/`; Cloud reads from `annotations/users/cloud/` and `admin/cloud/`.

In Cloud mode a **Sync from S3** button downloads the latest annotation files for all users from S3 before refreshing the table.

### Consensus table

| Column | Description |
|---|---|
| Block ID | `block_NNNN` or `block_UUID` identifier |
| Consensus | Majority-vote label across all annotators |
| Final Label | Admin override (amber background if set) |
| Status | Colour-coded: grey = unannotated, dark green = agree, red = disagree |
| `{username}` … | One column per annotator showing their individual label |

### Consensus algorithm

1. Collect all non-null labels for the block.
2. Count votes with `collections.Counter`.
3. The label with the highest vote count wins.
4. **Tie-breaking**: numerically smallest label wins.
5. `has_disagreement = True` when more than one distinct label was submitted.

### Override final label

1. Click a row to select a block (auto-play starts automatically in admin mode).
2. **Quick apply**: double-click any cell in a user column that shows a label (1, 2, 3…) — the label is applied immediately as the final label for that block.
3. **Manual apply**: use the spin box to choose a label, then click **Set Final Label**.

Both paths write to `annotations/admin/{local|cloud}/{dataset_slug}_final_labels.json` atomically and, in Cloud mode, also upload to S3.

### Export CSV

Columns: `block_id, consensus_label, final_label, has_disagreement, user_{username}_label (one per annotator), exported_at`.

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
│   ├── roles.json                      # Admin username list
│   └── classes.json                    # Class names + colors + channel names
│
├── data/                               # Gitignored — mount-point for block TIFFs
│   ├── Tile_X_0001_Y_0003_Z_0000/
│   │   └── ch_561/
│   │       └── blocks/
│   │           └── block_NNNN/
│   └── cloud_datasets/                 # Auto-created; S3 downloads land here
│       └── {experiment}/{tile}/{ch}/blocks/
│
├── annotations/                        # Gitignored — mount-point for annotation JSON
│   ├── users/
│   │   ├── local/
│   │   │   └── {username}/{experiment}/{slug}.json  # Per-dataset, local
│   │   ├── cloud/
│   │   │   └── {username}/{experiment}/{slug}.json  # Per-dataset, cloud
│   │   └── display_preferences/
│   │       └── {username}.json         # Global channel LUT/intensity settings
│   └── admin/
│       ├── local/
│       │   └── {dataset_slug}_final_labels.json     # Admin overrides, local
│       └── cloud/
│           └── {dataset_slug}_final_labels.json     # Admin overrides, cloud
│
├── src/
│   └── aind_proteomics_annotator/
│       ├── __init__.py
│       ├── __main__.py                 # Entry point: QApplication + LoginDialog + MainWindow
│       ├── config.py                   # AppConfig dataclass (env-var paths + S3 settings)
│       │
│       ├── models/
│       │   ├── annotation_store.py     # AnnotationStore + FinalLabelStore (JSON CRUD)
│       │   ├── block_registry.py       # Filesystem scan → list[BlockInfo]
│       │   └── user_session.py         # Active user: local/cloud store routing
│       │
│       ├── workers/
│       │   └── tiff_loader.py          # @thread_worker + BlockCache (LRU)
│       │
│       ├── gui/
│       │   ├── main_window.py          # QMainWindow: layout + shortcuts + S3 upload
│       │   ├── login_dialog.py         # Username prompt + S3 credential status
│       │   ├── block_list_panel.py     # Left sidebar (dataset list + block list)
│       │   ├── viewer_panel.py         # napari viewer embed + Z-slice autoplay
│       │   ├── channel_controls.py     # Per-channel LUT + range sliders
│       │   ├── bottom_panel.py         # Progress bar + status label
│       │   ├── overlay_widget.py       # Semi-transparent top-left QLabel
│       │   ├── admin_panel.py          # Admin review tab (Local/Cloud toggle)
│       │   └── s3_dataset_dialog.py    # S3 browser: listing, multi-select, batch download
│       │
│       └── utils/
│           ├── atomic_io.py            # atomic_write_json + read_json (NFS-safe)
│           ├── consensus.py            # Majority vote + build_consensus_table
│           ├── csv_exporter.py         # export_csv → CSV file
│           └── s3_client.py            # S3Client: list_datasets, download, upload, sync
│
└── tests/
    ├── conftest.py
    ├── test_atomic_io.py               # 6 tests
    ├── test_annotation_store.py        # 11 tests
    ├── test_block_registry.py          # 7 tests
    └── test_consensus.py               # 12 tests
```

---

## Architecture

### Startup sequence

```
python -m aind_proteomics_annotator
    │
    ├─ QApplication
    ├─ AppConfig.from_environment()        read env vars → paths + S3 settings
    ├─ LoginDialog.exec()                  blocking modal; shows S3 credential status
    ├─ _init_s3(config)                    probe AWS credential chain silently → S3Client | None
    ├─ BlockRegistry.scan()                glob data_root for block_NNNN / block_UUID dirs
    ├─ UserSession.load_or_create()
    │       ├─ mkdir users/local, users/cloud, users/display_preferences
    │       ├─ mkdir admin/local, admin/cloud
    │       ├─ AnnotationStore.load_or_create() × 2  (local + cloud)
    │       ├─ FinalLabelStore.load() × 2            (local + cloud)
    │       └─ read roles.json → set is_admin
    ├─ MainWindow(session, config, registry, s3_client)
    │       ├─ BlockListPanel.populate()
    │       ├─ S3 button enabled/disabled based on s3_client
    │       ├─ napari.Viewer(show=False)
    │       ├─ ChannelControlsPanel — loads display_preferences/{username}.json
    │       ├─ QShortcut(1…N, Space, ↑↓, R, Backspace, Alt+1…7)
    │       └─ AdminPanel (if is_admin)
    ├─ MainWindow.show()
    └─ app.exec()
```

### Annotation flow

```
Press key "2"
    → MainWindow._annotate(label=2)
    → AnnotationStore.set_label(block_id, 2)        atomic write to local or cloud JSON
    → ViewerPanel.show_label(2, "Class 2")
    → BlockListPanel.refresh_block_status(block_id)
    → check: all blocks in current dataset annotated?
        YES → _go_next_dataset()
                → _get_all_datasets() scan filesystem
                → find next dataset with annotated < total
                → _on_browse_requested(next_path)
                    → upload current cloud annotations to S3 (if applicable)
                    → _switch_dataset(next_path)
        NO  → if auto_advance → select_next_block()
```

### Cloud vs local routing

`UserSession.switch_data_root(path)` checks whether `path` resolves to somewhere inside `cloud_datasets/`. If yes, all annotation reads/writes go to `users/cloud/{username}.json`; otherwise to `users/local/{username}.json`. This is re-evaluated every time the active dataset changes.

### S3 dataset dialog thread lifecycle

Listing and downloading run in background `QThread` workers. Each thread:
- Has **no parent** so Qt does not destroy it when the dialog closes.
- Wires `worker.finished / worker.error → thread.quit`.
- Wires `thread.finished → thread.deleteLater + worker.deleteLater`.
- The dialog's `closeEvent` sets a cancellation flag, calls `thread.quit()`, and waits up to 5 s for the OS thread to exit before the dialog object is destroyed.

Sequential downloads use an identity-guarded null-out (`self._download_thread is t`) to prevent the previous thread's `finished` signal from wiping the reference to the next thread.

### napari embedding

```python
self._viewer = napari.Viewer(show=False)
qt_viewer_widget = self._viewer.window._qt_viewer   # semi-private attribute
layout.addWidget(qt_viewer_widget)                  # Qt reparents into our layout
```

> `_qt_viewer` carries a `FutureWarning` in napari < 0.6.0. The warning is suppressed at the call site.

---

## Multi-Machine / NFS Safety

Each annotator writes only their own `users/local/{username}.json` or `users/cloud/{username}.json`. These are independent files, so concurrent writes never target the same file. The only shared write target is `admin/{local|cloud}/final_labels.json`, written exclusively by admin users.

### Atomic write strategy (`utils/atomic_io.py`)

```
1.  tmp = same_dir / f".{stem}_{uuid4().hex}.tmp"   # unique name per write
2.  write JSON → tmp_file
3.  fh.flush() + os.fsync(fh.fileno())              # data → NFS server
4.  os.replace(tmp, target)                          # POSIX atomic rename
5.  os.fsync(dir_fd)                                 # rename → NFS server
```

- **No partial reads**: readers always see either the old or new complete file.
- **No collision**: UUID suffix means concurrent writers produce different temp names.
- **NFS durability**: both `fsync` calls ensure data and rename are on the server.

`read_json` retries up to 3 times with exponential backoff on `OSError` or `JSONDecodeError`.

---

## Running Tests

```bash
source .venv/bin/activate
PYTHONPATH=src pytest tests/ -v

# With coverage
PYTHONPATH=src pytest tests/ --cov=aind_proteomics_annotator --cov-report=term-missing
```

40 tests covering: atomic I/O, annotation store CRUD, block registry discovery, and consensus algorithms. GUI tests (Qt/napari) require a display and are not included in the default suite.

---

## Development

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

### Adding a new annotation class

1. Add an entry to `configs/classes.json` with `"name"` and `"color"`.
2. Keyboard shortcut for key **N** is bound automatically from the list length.
3. The overlay and block list colors are driven by `config.class_colors` — no code changes needed.

### Environment variable reference (full)

| Variable | Default | Notes |
|---|---|---|
| `ANNOTATOR_DATA_ROOT` | `./data/blocks` | Local blocks/ directory to annotate |
| `ANNOTATOR_ANNOTATIONS_ROOT` | `./annotations` | Contains `users/` and `admin/` subdirs |
| `ANNOTATOR_ROLES_FILE` | `./configs/roles.json` | Admin username list |
| `ANNOTATOR_CLASSES_FILE` | `./configs/classes.json` | Class + channel definitions |
| `ANNOTATOR_S3_DATA_BUCKET` | `""` | S3 source bucket (activates S3 features) |
| `ANNOTATOR_S3_DATA_PREFIX` | `""` | Key prefix within source bucket |
| `ANNOTATOR_S3_OUTPUT_BUCKET` | `""` | S3 destination bucket for annotation uploads |
| `ANNOTATOR_S3_OUTPUT_PREFIX` | `annotations` | Key prefix for annotation uploads |
| `ANNOTATOR_S3_PROFILE` | `""` | AWS credentials profile name |
| `ANNOTATOR_S3_LOCAL_CACHE` | *(auto)* | Override for downloaded dataset cache directory |
| `QT_API` | *(auto)* | Force Qt binding: `pyqt5`, `pyside6`, etc. |

---

## License

MIT — see [LICENSE](LICENSE).
