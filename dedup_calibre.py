"""Remove duplicate highlights and tombstone entries from Calibre's metadata.db.

Duplicates are defined as rows in the annotations table with the same
(book, searchable_text) pair. When duplicates exist, only the oldest row
(lowest id) is kept.

Additionally, all "removed: true" tombstone entries (empty-text deletion
markers) are purged.

Usage:
    python dedup_calibre.py <path_to_metadata.db>            # dry-run (preview)
    python dedup_calibre.py <path_to_metadata.db> --apply    # actually delete
"""

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path


def find_tombstones(cur: sqlite3.Cursor) -> list:
    """Return ids of all 'removed: true' tombstone annotations."""
    rows = cur.execute(
        "SELECT id, annot_data FROM annotations "
        "WHERE user_type = 'local' AND annot_type = 'highlight'"
    ).fetchall()

    tombstone_ids = []
    for row_id, annot_data_str in rows:
        try:
            annot_data = json.loads(annot_data_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if annot_data.get("removed", False):
            tombstone_ids.append(row_id)

    return tombstone_ids


def find_text_duplicates(cur: sqlite3.Cursor) -> list:
    """Return ids of duplicate highlights (same book + text), keeping the oldest."""
    # Find groups with more than one row
    groups = cur.execute(
        "SELECT book, searchable_text, GROUP_CONCAT(id) as ids, COUNT(*) as cnt "
        "FROM annotations "
        "WHERE user_type = 'local' AND annot_type = 'highlight' "
        "GROUP BY book, searchable_text "
        "HAVING cnt > 1"
    ).fetchall()

    ids_to_delete = []
    for book, text, ids_str, cnt in groups:
        ids = sorted(int(i) for i in ids_str.split(","))
        # Keep the oldest (lowest id), delete the rest
        ids_to_delete.extend(ids[1:])

    return ids_to_delete


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate highlights in Calibre metadata.db"
    )
    parser.add_argument("db_path", help="Path to Calibre metadata.db")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete duplicates (default is dry-run)",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: {db_path} does not exist")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Count total before
    total_before = cur.execute(
        "SELECT COUNT(*) FROM annotations "
        "WHERE user_type = 'local' AND annot_type = 'highlight'"
    ).fetchone()[0]

    # Find what to delete
    tombstone_ids = find_tombstones(cur)
    duplicate_ids = find_text_duplicates(cur)

    # Remove overlap (tombstones that are also in duplicate groups)
    tombstone_set = set(tombstone_ids)
    duplicate_set = set(duplicate_ids)
    # Some tombstones might be in duplicate groups — don't double-count
    overlap = tombstone_set & duplicate_set
    all_ids = tombstone_set | duplicate_set

    print(f"Total highlights in DB:        {total_before}")
    print(f"Tombstone entries to remove:   {len(tombstone_ids)}")
    print(f"Text-duplicate rows to remove: {len(duplicate_ids)}")
    if overlap:
        print(f"  (overlap with tombstones:    {len(overlap)})")
    print(f"Total rows to delete:          {len(all_ids)}")
    print(f"Highlights remaining after:    {total_before - len(all_ids)}")
    print()

    if not all_ids:
        print("Nothing to clean up.")
        return

    if not args.apply:
        print("DRY RUN — no changes made. Pass --apply to execute.")
        return

    # Create backup
    backup_path = db_path.with_suffix(".db.bak")
    print(f"Creating backup at {backup_path} ...")
    shutil.copy2(db_path, backup_path)

    # Delete in batches
    ids_list = sorted(all_ids)
    batch_size = 500
    deleted = 0
    for i in range(0, len(ids_list), batch_size):
        batch = ids_list[i : i + batch_size]
        placeholders = ",".join("?" for _ in batch)
        cur.execute(f"DELETE FROM annotations WHERE id IN ({placeholders})", batch)
        deleted += cur.rowcount

    con.commit()

    # Count total after
    total_after = cur.execute(
        "SELECT COUNT(*) FROM annotations "
        "WHERE user_type = 'local' AND annot_type = 'highlight'"
    ).fetchone()[0]

    con.close()

    print(f"Deleted {deleted} rows.")
    print(f"Highlights now in DB: {total_after}")
    print(f"Backup saved at: {backup_path}")


if __name__ == "__main__":
    main()
