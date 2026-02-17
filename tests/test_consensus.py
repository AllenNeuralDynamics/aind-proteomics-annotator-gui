"""Tests for utils/consensus.py."""

import pytest

from aind_proteomics_annotator.utils.consensus import (
    build_consensus_table,
    compute_consensus,
)


class TestComputeConsensus:
    def test_unanimous(self) -> None:
        label, disagree = compute_consensus([1, 1, 1])
        assert label == 1
        assert disagree is False

    def test_majority(self) -> None:
        label, disagree = compute_consensus([1, 1, 2])
        assert label == 1
        assert disagree is True

    def test_tie_picks_smallest(self) -> None:
        label, disagree = compute_consensus([1, 2])
        assert label == 1
        assert disagree is True

    def test_all_none_returns_none(self) -> None:
        label, disagree = compute_consensus([None, None])
        assert label is None
        assert disagree is False

    def test_empty_list(self) -> None:
        label, disagree = compute_consensus([])
        assert label is None
        assert disagree is False

    def test_ignores_none(self) -> None:
        label, disagree = compute_consensus([None, 2, 2])
        assert label == 2
        assert disagree is False

    def test_single_vote(self) -> None:
        label, disagree = compute_consensus([3])
        assert label == 3
        assert disagree is False

    def test_three_way_tie(self) -> None:
        label, disagree = compute_consensus([1, 2, 3])
        assert label == 1  # smallest wins
        assert disagree is True


class TestBuildConsensusTable:
    def test_basic(self) -> None:
        all_user = {
            "alice": {"block_0001": {"label": 1}},
            "bob": {"block_0001": {"label": 1}},
        }
        rows = build_consensus_table(all_user, ["block_0001"])
        assert len(rows) == 1
        row = rows[0]
        assert row["block_id"] == "block_0001"
        assert row["consensus"] == 1
        assert row["disagreement"] is False
        assert row["user_labels"] == {"alice": 1, "bob": 1}

    def test_disagreement(self) -> None:
        all_user = {
            "alice": {"block_0001": {"label": 1}},
            "bob": {"block_0001": {"label": 2}},
        }
        rows = build_consensus_table(all_user, ["block_0001"])
        assert rows[0]["disagreement"] is True

    def test_unannotated_block(self) -> None:
        all_user = {
            "alice": {},
        }
        rows = build_consensus_table(all_user, ["block_0001"])
        assert rows[0]["consensus"] is None
        assert rows[0]["user_labels"] == {}

    def test_multiple_blocks(self) -> None:
        all_user = {
            "alice": {
                "block_0001": {"label": 1},
                "block_0002": {"label": 2},
            },
        }
        rows = build_consensus_table(all_user, ["block_0001", "block_0002"])
        assert len(rows) == 2
        assert rows[0]["block_id"] == "block_0001"
        assert rows[1]["block_id"] == "block_0002"
