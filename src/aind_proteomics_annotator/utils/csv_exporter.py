"""Export annotation summaries to CSV for downstream dataset use."""

import csv
from datetime import datetime, timezone
from pathlib import Path


def export_csv(
    consensus_rows: list,
    final_labels: dict,
    output_path: Path,
    usernames: list,
) -> None:
    """Write annotation summary to a CSV file.

    Parameters
    ----------
    consensus_rows:
        Output of :func:`build_consensus_table` – one dict per block.
    final_labels:
        Output of :meth:`FinalLabelStore.all_labels`.
    output_path:
        Destination path for the CSV file.
    usernames:
        All annotator usernames (for per-user columns).

    CSV columns
    -----------
    block_id, consensus_label, final_label, has_disagreement,
    user_{username}_label  (one per annotator, sorted),
    exported_at
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sorted_users = sorted(usernames)
    fieldnames = (
        ["block_id", "consensus_label", "final_label", "has_disagreement"]
        + [f"user_{u}_label" for u in sorted_users]
        + ["exported_at"]
    )
    exported_at = datetime.now(timezone.utc).isoformat()

    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        for row in consensus_rows:
            fl_entry = final_labels.get(row["block_id"], {})
            csv_row: dict = {
                "block_id": row["block_id"],
                "consensus_label": row["consensus"] if row["consensus"] is not None else "",
                "final_label": fl_entry.get("final_label", ""),
                "has_disagreement": row["disagreement"],
                "exported_at": exported_at,
            }
            for u in sorted_users:
                csv_row[f"user_{u}_label"] = row["user_labels"].get(u, "")

            writer.writerow(csv_row)
