"""Discovers and indexes block_xxxx/ directories under the data root."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Matches block_0001, block_0042, block_9999, etc.
_BLOCK_PATTERN = re.compile(r"^block_\d{4}$")


@dataclass
class BlockInfo:
    """Metadata for one annotatable block."""

    block_id: str
    path: Path
    tiff_files: list = field(default_factory=list)

    @property
    def channel_count(self) -> int:
        return len(self.tiff_files)


class BlockRegistry:
    """Scans *data_root* and builds an ordered list of BlockInfo objects.

    Call scan() once at startup; re-call if the directory changes.
    """

    def __init__(self, data_root: Path) -> None:
        self._data_root = Path(data_root)
        self._blocks: list[BlockInfo] = []

    def scan(self) -> None:
        """Populate the block list from the filesystem."""
        self._blocks = []
        if not self._data_root.exists():
            return

        for entry in sorted(self._data_root.iterdir()):
            if entry.is_dir() and _BLOCK_PATTERN.match(entry.name):
                tiffs = sorted(entry.glob("*.tiff")) + sorted(entry.glob("*.tif"))
                self._blocks.append(
                    BlockInfo(
                        block_id=entry.name,
                        path=entry,
                        tiff_files=tiffs,
                    )
                )

    def all_blocks(self) -> list:
        """Return all discovered blocks in sorted order."""
        return list(self._blocks)

    def get_block(self, block_id: str) -> Optional[BlockInfo]:
        """Return the BlockInfo for *block_id*, or None if not found."""
        for b in self._blocks:
            if b.block_id == block_id:
                return b
        return None

    def block_count(self) -> int:
        return len(self._blocks)

    def rescan(self, new_root: "Path | None" = None) -> None:
        """Change the data root (optional) and re-scan the filesystem."""
        if new_root is not None:
            self._data_root = Path(new_root)
        self.scan()
