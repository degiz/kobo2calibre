#!/usr/bin/env python3
"""
Script to remove all highlights belonging to a specific book from Kobo database.
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Dict, Any


def read_highlights_from_kobo(
    db_path: str, title: str, author: str
) -> List[Dict[str, Any]]:
    """
    Read all highlights for a book from the Kobo device database.

    Args:
        db_path: Path to KoboReader.sqlite database
        title: Book title to match
        author: Book author to match

    Returns:
        List of highlight dictionaries with all bookmark fields
    """
    db_file = Path(db_path)

    if not db_file.exists():
        print(f"Error: Database file not found at {db_path}")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row  # Enable dictionary-like access
    cur = con.cursor()

    # Find the ContentID for the book
    query = """
        SELECT ContentID, Title, Attribution 
        FROM content 
        WHERE Title LIKE ? AND Attribution LIKE ?
    """

    results = cur.execute(query, (f"%{title}%", f"%{author}%")).fetchall()

    if not results:
        print(f"No book found with title '{title}' and author '{author}'")
        con.close()
        return []

    all_highlights = []

    for row in results:
        content_id = row["ContentID"]

        # Get all bookmarks for this book
        highlights_query = "SELECT * FROM Bookmark WHERE VolumeID = ?"
        highlights = cur.execute(highlights_query, (content_id,)).fetchall()

        for highlight in highlights:
            # Convert Row object to dict
            highlight_dict = dict(highlight)
            all_highlights.append(highlight_dict)

    con.close()
    return all_highlights


def insert_highlights_to_kobo(db_path: str, highlights: List[Dict[str, Any]]):
    """
    Insert highlights back into the Kobo device database.

    Args:
        db_path: Path to KoboReader.sqlite database
        highlights: List of highlight dictionaries to insert
    """
    db_file = Path(db_path)

    if not db_file.exists():
        print(f"Error: Database file not found at {db_path}")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Get all column names from the first highlight
    if not highlights:
        print("No highlights to insert")
        con.close()
        return

    columns = list(highlights[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    columns_str = ", ".join(columns)

    insert_query = f"INSERT INTO Bookmark ({columns_str}) VALUES ({placeholders})"

    inserted_count = 0
    for highlight in highlights:
        try:
            values = [highlight[col] for col in columns]
            cur.execute(insert_query, values)
            inserted_count += 1
        except sqlite3.IntegrityError as e:
            print(
                f"  Warning: Skipping duplicate highlight {highlight.get('BookmarkID')}: {e}"
            )

    con.commit()
    con.close()

    print(f"✓ Inserted {inserted_count}/{len(highlights)} highlight(s)")


def remove_highlights_from_kobo(
    db_path: str, title: str, author: str, dry_run: bool = False
):
    """
    Remove all highlights for a book from the Kobo device database.

    Args:
        db_path: Path to KoboReader.sqlite database
        title: Book title to match
        author: Book author to match
        dry_run: If True, only show what would be deleted without actually deleting
    """
    db_file = Path(db_path)

    if not db_file.exists():
        print(f"Error: Database file not found at {db_path}")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Find the ContentID for the book (which is used as VolumeID in Bookmark table)
    query = """
        SELECT ContentID, Title, Attribution 
        FROM content 
        WHERE Title LIKE ? AND Attribution LIKE ?
    """

    results = cur.execute(query, (f"%{title}%", f"%{author}%")).fetchall()

    if not results:
        print(f"No book found with title '{title}' and author '{author}'")
        con.close()
        return

    print(f"Found {len(results)} matching book(s):")
    for content_id, book_title, book_author in results:
        print(f"  - ContentID: {content_id}")
        print(f"    Title: {book_title}")
        print(f"    Author: {book_author}")

    # Get highlights count for each book
    for content_id, book_title, book_author in results:
        count_query = "SELECT COUNT(*) FROM Bookmark WHERE VolumeID = ?"
        count = cur.execute(count_query, (content_id,)).fetchone()[0]

        print(f"\nFound {count} highlight(s) for '{book_title}'")

        if count > 0:
            if dry_run:
                print(f"[DRY RUN] Would delete {count} highlight(s)")
            else:
                delete_query = "DELETE FROM Bookmark WHERE VolumeID = ?"
                cur.execute(delete_query, (content_id,))
                con.commit()
                print(f"✓ Deleted {count} highlight(s)")

    con.close()
    print("\nDone!")


def read_highlights_from_calibre(
    db_path: str, title: str, author: str
) -> List[Dict[str, Any]]:
    """
    Read all highlights for a book from the Calibre library database.

    Args:
        db_path: Path to Calibre metadata.db database
        title: Book title to match
        author: Book author to match

    Returns:
        List of annotation dictionaries with all fields and parsed annot_data
    """
    db_file = Path(db_path)

    if not db_file.exists():
        print(f"Error: Database file not found at {db_path}")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Find the book by title and author
    query = """
        SELECT b.id, b.title, b.author_sort 
        FROM books b
        WHERE b.title LIKE ? AND b.author_sort LIKE ?
    """

    results = cur.execute(query, (f"%{title}%", f"%{author}%")).fetchall()

    if not results:
        print(f"No book found in Calibre with title '{title}' and author '{author}'")
        con.close()
        return []

    all_highlights = []

    for row in results:
        book_id = row["id"]

        # Get all annotations for this book
        annotations_query = """
            SELECT * FROM annotations 
            WHERE book = ? AND user_type = 'local'
        """
        annotations = cur.execute(annotations_query, (book_id,)).fetchall()

        for annot in annotations:
            # Convert Row object to dict
            annot_dict = dict(annot)
            # Parse the JSON annot_data field
            annot_dict["annot_data_parsed"] = json.loads(annot_dict["annot_data"])
            all_highlights.append(annot_dict)

    con.close()
    return all_highlights


if __name__ == "__main__":
    # Configuration
    KOBO_DB_PATH = "/Volumes/KOBOeReader/.kobo/KoboReader.sqlite"
    CALIBRE_DB_PATH = "/Volumes/Stuff/Calibre/metadata.db"
    BOOK_TITLE = "Old Format"
    BOOK_AUTHOR = "Anonymous Philosopher"
    KOBO_BACKUP_FILE = "kobo_highlights_backup_old.json"
    CALIBRE_BACKUP_FILE = "calibre_highlights_backup.json"

    # Set to True to preview what would be deleted without actually deleting
    DRY_RUN = False

    print(f"Kobo & Calibre Highlight Manager")
    print(f"Kobo Database: {KOBO_DB_PATH}")
    print(f"Calibre Database: {CALIBRE_DB_PATH}")
    print(f"Target Book: '{BOOK_TITLE}' by {BOOK_AUTHOR}")
    print("=" * 60)

    # Read highlights from Calibre
    print("\n[1] Reading highlights from Calibre...")
    calibre_highlights = read_highlights_from_calibre(
        CALIBRE_DB_PATH, BOOK_TITLE, BOOK_AUTHOR
    )
    print(f"Found {len(calibre_highlights)} highlight(s) in Calibre")

    if calibre_highlights:
        print("\nCalibre highlight details:")
        for i, h in enumerate(calibre_highlights, 1):
            data = h["annot_data_parsed"]
            print(f"  {i}. Text: {data.get('highlighted_text', '')[:50]}...")
            print(f"     Style: {data.get('style', {}).get('which', 'unknown')}")
            print(f"     CFI: {data.get('start_cfi', '')} → {data.get('end_cfi', '')}")

        # Save Calibre highlights to file
        with open(CALIBRE_BACKUP_FILE, "w") as f:
            json.dump(calibre_highlights, f, indent=2)
        print(f"\n✓ Backed up Calibre highlights to {CALIBRE_BACKUP_FILE}")

    # Load Kobo highlights from backup if it exists
    kobo_highlights = []
    if Path(KOBO_BACKUP_FILE).exists():
        print(f"\n[2] Loading Kobo highlights from {KOBO_BACKUP_FILE}...")
        with open(KOBO_BACKUP_FILE) as f:
            kobo_highlights = json.load(f)
        print(f"Loaded {len(kobo_highlights)} highlight(s) from Kobo backup")

        print("\nKobo highlight details:")
        for i, h in enumerate(kobo_highlights, 1):
            print(f"  {i}. Text: {h.get('Text', '')[:50]}...")
            print(f"     Color: {h.get('Color', 'unknown')}")
            print(f"     Path: {h.get('StartContainerPath', '')}")

    print("\n" + "=" * 60)
    print("Comparison complete!")
