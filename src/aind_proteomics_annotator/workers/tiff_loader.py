"""Async TIFF loading worker with LRU block cache.

Uses napari's @thread_worker to load TIFF files in a background QThread,
keeping the Qt main thread and napari canvas responsive during disk I/O.

Usage
-----
worker = load_block_worker(tiff_paths, block_id)
worker.returned.connect(callback)   # callback receives (block_id, list[ndarray])
worker.errored.connect(error_handler)
worker.start()
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Optional

import numpy as np
import tifffile
from napari.qt.threading import thread_worker


class BlockCache:
    """Simple LRU cache mapping block_id → list of channel arrays.

    Not thread-safe; access only from the Qt main thread.
    """

    def __init__(self, max_size: int = 3) -> None:
        self._cache: OrderedDict[str, list] = OrderedDict()
        self._max_size = max_size

    def get(self, block_id: str) -> Optional[list]:
        """Return cached arrays for *block_id*, or None if not cached."""
        if block_id in self._cache:
            self._cache.move_to_end(block_id)
            return self._cache[block_id]
        return None

    def put(self, block_id: str, arrays: list) -> None:
        """Cache *arrays* for *block_id*, evicting the oldest entry if full."""
        if block_id in self._cache:
            self._cache.move_to_end(block_id)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            self._cache[block_id] = arrays

    def clear(self) -> None:
        self._cache.clear()


# Module-level cache; replaced per-Viewer if needed.
_default_cache = BlockCache()


@thread_worker
def load_block_worker(tiff_paths: list, block_id: str, cache: Optional[BlockCache] = None):
    """Background worker that loads all channels for a block.

    Parameters
    ----------
    tiff_paths:
        Ordered list of Path objects, one per channel.
    block_id:
        Identifier for the block (used as cache key).
    cache:
        BlockCache instance. Defaults to the module-level cache if None.

    Yields / Returns
    ----------------
    tuple[str, list[np.ndarray]]
        (block_id, list_of_channel_arrays).  Each array has shape (Z, Y, X),
        dtype float32.
    """
    _cache = cache if cache is not None else _default_cache

    cached = _cache.get(block_id)
    if cached is not None:
        return block_id, cached

    arrays = []
    for p in tiff_paths:
        arr = tifffile.imread(str(p))
        arr = np.asarray(arr, dtype=np.float32)
        arrays.append(arr)

    _cache.put(block_id, arrays)
    return block_id, arrays


@thread_worker
def preload_block_worker(block_infos: list, cache: BlockCache):
    """Background worker that pre-warms the cache for a list of BlockInfo objects.

    Skips any block_id already present in the cache.  The return value is
    intentionally ignored by the caller — the side-effect of populating the
    cache is all that matters.

    Parameters
    ----------
    block_infos:
        Ordered list of :class:`BlockInfo` objects to preload.
    cache:
        The shared :class:`BlockCache` instance.
    """
    for info in block_infos:
        if cache.get(info.block_id) is not None:
            continue  # already cached
        arrays = []
        for p in info.tiff_files:
            arr = tifffile.imread(str(p))
            arrays.append(np.asarray(arr, dtype=np.float32))
        cache.put(info.block_id, arrays)
