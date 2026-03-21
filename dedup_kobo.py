"""Remove duplicate highlights from Kobo's KoboReader.sqlite.

Duplicates are defined as rows in the Bookmark table with the same
(VolumeID, Text) pair. When duplicates exist, only the oldest row
(earliest DateCreated) is kept.

Usage:
    python dedup_kobo.py <path_to_KoboReader.sqlite>            # dry-run (preview)
    python dedup_kobo.py <path_to_KoboReader.sqlite> --apply    # actually delete
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


def find_text_duplicates(cur: sqlite3.Cursor) -> list:
    """Return BookmarkIDs of duplicate highlights (same VolumeID + Text), keeping the oldest."""
    groups = cur.execute(
        "SELECT VolumeID, Text, GROUP_CONCAT(BookmarkID, '||') as ids, "
        "GROUP_CONCAT(DateCreated, '||') as dates, COUNT(*) as cnt "
        "FROM Bookmark "
        "WHERE Text != '' "
        "GROUP BY VolumeID, Text "
        "HAVING cnt > 1"
    ).fetchall()

    ids_to_delete = []
    for volume_id, text, ids_str, dates_str, cnt in groups:
        ids = ids_str.split("||")
        dates = dates_str.split("||")
        # Sort by DateCreated (ascending), keep the oldest
        paired = sorted(zip(dates, ids), key=lambda x: x[0] or "")
        # Keep the first (oldest), delete the rest
        ids_to_delete.extend(bookmark_id for _, bookmark_id in paired[1:])

    return ids_to_delete


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate highlights in Kobo KoboReader.sqlite"
    )
    parser.add_argument("db_path", help="Path to KoboReader.sqlite")
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
        "SELECT COUNT(*) FROM Bookmark WHERE Text != ''"
    ).fetchone()[0]

    # Find what to delete
    duplicate_ids = find_text_duplicates(cur)

    print(f"Total highlights in DB:        {total_before}")
    print(f"Duplicate rows to remove:      {len(duplicate_ids)}")
    print(f"Highlights remaining after:    {total_before - len(duplicate_ids)}")
    print()

    if not duplicate_ids:
        print("Nothing to clean up.")
        return

    if not args.apply:
        print("DRY RUN — no changes made. Pass --apply to execute.")
        return

    # Create backup
    backup_path = db_path.with_suffix(".sqlite.bak")
    print(f"Creating backup at {backup_path} ...")
    shutil.copy2(db_path, backup_path)

    # Delete in batches
    deleted = 0
    batch_size = 500
    for i in range(0, len(duplicate_ids), batch_size):
        batch = duplicate_ids[i : i + batch_size]
        placeholders = ",".join("?" for _ in batch)
        cur.execute(f"DELETE FROM Bookmark WHERE BookmarkID IN ({placeholders})", batch)
        deleted += cur.rowcount

    con.commit()

    # Count total after
    total_after = cur.execute(
        "SELECT COUNT(*) FROM Bookmark WHERE Text != ''"
    ).fetchone()[0]

    con.close()

    print(f"Deleted {deleted} rows.")
    print(f"Highlights now in DB: {total_after}")
    print(f"Backup saved at: {backup_path}")


if __name__ == "__main__":
    main()
