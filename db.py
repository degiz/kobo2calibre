import json
import logging
import pathlib
import sqlite3
from collections import namedtuple
from typing import Dict, List, Tuple

import calibre

logger = logging.getLogger(__name__)

KoboHighlight = namedtuple(
    "KoboHighlight",
    ["start_path", "end_path", "start_offset", "end_offset", "text", "content_path"],
)

CalibreHighlight = namedtuple(
    "CalibreHighlight",
    [
        "book",
        "format",
        "user_type",
        "user",
        "timestamp",
        "annot_id",
        "annot_type",
        "highlight",
        "searchable_text",
    ],
)


def get_likely_book_path_from_calibre(
    calibre_db_path: pathlib.Path, kobo_volume: pathlib.Path, book_lpath: str
) -> Tuple[int, str]:
    con = sqlite3.connect(calibre_db_path)
    cur = con.cursor()

    book_lpath = book_lpath.split("/")[-1]

    book_id = calibre.get_calibre_book_id(kobo_volume, book_lpath)

    book_path = cur.execute(f"SELECT path FROM books WHERE id = {book_id}").fetchone()[
        0
    ]
    con.close()

    return book_id, book_path


def get_dictinct_highlights_from_kobo(
    input_kobo_db: pathlib.Path,
) -> Dict[str, List[KoboHighlight]]:
    con = sqlite3.connect(input_kobo_db)
    cur = con.cursor()

    result = {}
    for distinct_name in cur.execute("SELECT DISTINCT `VolumeID` FROM `Bookmark`"):
        name = distinct_name[0]
        if name not in result:
            result[name] = []

        cur1 = con.cursor()
        for row in cur1.execute(
            f"SELECT * FROM `Bookmark` WHERE `VolumeID` = '{name}' AND text !=''"
        ):
            content_path = row[2].split("epub!")[-1]
            content_path = content_path.lstrip("!")
            content_path = content_path.replace("!", "/")
            if "#" in content_path:
                content_path = content_path.split("#")[-2]
            if not content_path:
                continue

            highlight = KoboHighlight(
                row[3], row[6], row[5], row[8], row[9], content_path
            )
            result[name].append(highlight)

    con.close()
    return result


def insert_highlights_into_calibre(
    output_calibre_db: pathlib.Path, books_highlights: List[CalibreHighlight]
) -> None:
    con = sqlite3.connect(output_calibre_db)
    cur = con.cursor()

    actually_inserted_count = 0
    for h in books_highlights:

        # check for duplicates
        if cur.execute(
            f"SELECT id from annotations where annot_id = '{h.annot_id}'"
        ).fetchone():
            logger.debug(
                f"Annotation with id {h.annot_id} (from {h.book}) already exists in db"
            )
            continue

        query = (
            f"INSERT INTO annotations( "
            f"book, format, user_type, user, "
            f"timestamp, annot_id, annot_type, "
            f"annot_data, searchable_text) VALUES("
            f"?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        logger.debug(f"Query: {query}")
        cur.execute(
            query,
            (
                h.book,
                h.format,
                h.user_type,
                h.user,
                h.timestamp,
                h.highlight["uuid"],
                h.annot_type,
                json.dumps(h.highlight),
                h.searchable_text,
            ),
        )
        actually_inserted_count += 1

    logger.info(f"Inserted {actually_inserted_count} new highlights")

    con.commit()
    con.close()
