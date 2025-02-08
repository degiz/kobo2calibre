import json
import logging
import pathlib
import sqlite3
from collections import namedtuple
from typing import Dict, List, Tuple

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


def get_calibre_book_id(kobo_volume: pathlib.Path, lpath: str) -> int:
    """Get the calibre book id from the lpath of the book in the kobo db."""
    calibre_device_metadata = kobo_volume.resolve() / "metadata.calibre"
    with open(calibre_device_metadata) as f:
        metadata = json.load(f)
        target_book = list(
            filter(lambda x: x.get("lpath").split("/")[-1] == lpath, metadata)
        )[0]
        return target_book["application_id"]


def get_likely_book_path_from_calibre(
    calibre_db_path: pathlib.Path, kobo_volume: pathlib.Path, book_lpath: str
) -> Tuple[int, str]:
    """Get the likely book path from the calibre db."""
    con = sqlite3.connect(calibre_db_path)
    cur = con.cursor()

    book_lpath = book_lpath.split("/")[-1]

    book_id = get_calibre_book_id(kobo_volume, book_lpath)

    book_path = cur.execute(f"SELECT path FROM books WHERE id = {book_id}").fetchone()[
        0
    ]
    con.close()

    return book_id, book_path


def get_book_path_by_title(
    calibre_db_path: pathlib.Path, title: str
) -> Tuple[int, str]:
    """Get the likely book path from the calibre db."""
    con = sqlite3.connect(calibre_db_path)
    cur = con.cursor()

    book_id = cur.execute(f"SELECT id FROM books WHERE title = '{title}'").fetchone()[0]
    book_path = cur.execute(
        f"SELECT path FROM books WHERE title = '{title}'"
    ).fetchone()[0]
    con.close()

    return book_id, book_path


def get_dictinct_highlights_from_kobo(
    input_kobo_db: pathlib.Path,
) -> Dict[str, List[KoboHighlight]]:
    """Get distinct highlights from the kobo db."""
    con = sqlite3.connect(input_kobo_db)
    cur = con.cursor()

    result = {}
    for distinct_name in cur.execute("SELECT DISTINCT `VolumeID` FROM `Bookmark`"):
        name = distinct_name[0]

        cur_x = con.cursor()
        title = cur_x.execute(
            "SELECT title from `tolino_contentItem` where uuid = ?", (name,)
        ).fetchone()[0]
        # if title:
        #     title = title.split("/")[-1].replace("+", " ")
        cur_x.close()

        # skip name if it looks like a UUID
        # if len(name) == 36 and "-" in name:
        #     continue

        if title not in result:
            result[title] = []

        cur1 = con.cursor()
        for row in cur1.execute(
            f"SELECT * FROM `Bookmark` WHERE `VolumeID` = '{name}' AND text !=''"
        ):
            # get content path from CFI like OPS/ch1-3.xhtml#point(/1/4/2/3/1:0)
            content_path = row[3].split("#")[0]

            highlight = KoboHighlight(
                row[3], row[6], row[5], row[8], row[9], content_path
            )
            result[title].append(highlight)

    con.close()
    return result


def get_highlights_from_kobo_by_book(
    input_kobo_db: pathlib.Path, book: str
) -> List[KoboHighlight]:
    """Get highlights from the kobo db for a specific book."""
    con = sqlite3.connect(input_kobo_db)

    result = []

    cur1 = con.cursor()
    for row in cur1.execute(
        f"SELECT * FROM `Bookmark` WHERE `VolumeID` = '{book}' AND text !=''"
    ):
        content_path = row[2].split("epub!")[-1]
        content_path = content_path.lstrip("!")
        content_path = content_path.replace("!", "/")
        if "#" in content_path:
            content_path = content_path.split("#")[-2]
        if not content_path:
            continue

        highlight = KoboHighlight(row[3], row[6], row[5], row[8], row[9], content_path)
        result.append(highlight)

    con.close()
    return result


def insert_highlights_into_calibre(
    output_calibre_db: pathlib.Path, books_highlights: List[CalibreHighlight]
) -> int:
    """Insert highlights into the calibre db."""
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
            "INSERT INTO annotations( "
            "book, format, user_type, user, "
            "timestamp, annot_id, annot_type, "
            "annot_data, searchable_text) VALUES("
            "?, ?, ?, ?, ?, ?, ?, ?, ?)"
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
    return actually_inserted_count
