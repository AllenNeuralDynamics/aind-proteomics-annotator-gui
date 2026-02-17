"""Majority-vote consensus calculation for the admin review panel."""

from collections import Counter
from typing import Optional


def compute_consensus(
    labels: list,
) -> tuple:
    """Compute majority-vote consensus and disagreement flag.

    Parameters
    ----------
    labels:
        List of integer labels (may contain None for unannotated entries).

    Returns
    -------
    (consensus_label, has_disagreement)
        *consensus_label* is None if no valid votes exist.
        *has_disagreement* is True if the vote is not unanimous among
        the valid labels (ties count as disagreement).
    """
    valid = [lbl for lbl in labels if lbl is not None]
    if not valid:
        return None, False

    counter = Counter(valid)
    has_disagreement = len(counter) > 1

    max_count = counter.most_common(1)[0][1]
    # All labels that share the highest vote count.
    leaders = sorted(lbl for lbl, cnt in counter.items() if cnt == max_count)
    consensus_label = leaders[0]  # tie-break: smallest label wins

    return consensus_label, has_disagreement


def build_consensus_table(
    all_user_annotations: dict,
    block_ids: list,
) -> list:
    """Build a per-block consensus summary suitable for the admin table.

    Parameters
    ----------
    all_user_annotations:
        ``{username: {block_id: {"label": int, ...}}}``
    block_ids:
        Ordered list of all block IDs (from :class:`BlockRegistry`).

    Returns
    -------
    list[dict]
        Each dict has keys: ``block_id``, ``user_labels``, ``consensus``,
        ``disagreement``.
    """
    rows = []
    for block_id in block_ids:
        user_labels: dict = {}
        for username, annotations in all_user_annotations.items():
            entry = annotations.get(block_id)
            if entry:
                user_labels[username] = entry.get("label")

        consensus, disagreement = compute_consensus(list(user_labels.values()))
        rows.append(
            {
                "block_id": block_id,
                "user_labels": user_labels,
                "consensus": consensus,
                "disagreement": disagreement,
            }
        )
    return rows
