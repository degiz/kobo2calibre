import json
from datetime import datetime
import logging
import pathlib
import sqlite3
from collections import namedtuple
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

KoboSourceHighlight = namedtuple(
    "KoboHighlight",
    [
        "start_path",
        "end_path",
        "start_offset",
        "end_offset",
        "text",
        "content_path",
        "color",
    ],
)

CalibreTargetHighlight = namedtuple(
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

CalibreSourceHighlight = namedtuple(
    "CalibreSourceHighlight",
    ["start_cfi", "end_cfi", "spine_name", "highlighted_text", "color"],
)


KoboTargetHighlight = namedtuple(
    "KoboTargetHighlight",
    [
        "start_path",
        "end_path",
        "start_offset",
        "end_offset",
        "text",
        "volume_id",
        "content_id",
        "color",
        "uuid",
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


def get_kobo_content_path_by_book_id(kobo_volume: pathlib.Path, book_id: int) -> str:
    calibre_device_metadata = kobo_volume.resolve() / "metadata.calibre"
    with open(calibre_device_metadata) as f:
        metadata = json.load(f)
        target_book = list(
            filter(lambda x: x.get("application_id") == book_id, metadata)
        )[0].get("lpath")
        return target_book


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


def get_likely_book_path_from_calibre_by_id(
    calibre_db_path: pathlib.Path, book_id: int
) -> str:
    """Get the likely book path from the calibre db."""
    con = sqlite3.connect(calibre_db_path)
    cur = con.cursor()

    book_path = cur.execute(f"SELECT path FROM books WHERE id = {book_id}").fetchone()[
        0
    ]
    con.close()

    return book_path


def get_dictinct_highlights_from_kobo(
    input_kobo_db: pathlib.Path,
) -> Dict[str, List[KoboSourceHighlight]]:
    """Get distinct highlights from the kobo db."""
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

            highlight = KoboSourceHighlight(
                row[3],
                row[6],
                row[5],
                row[8],
                row[9],
                content_path,
                row[24],
            )
            result[name].append(highlight)

    con.close()
    return result


def get_highlights_from_calibre_by_book_id(
    input_calibre_db: pathlib.Path, book_id: int
) -> List[CalibreSourceHighlight]:
    """Get distinct highlights from the calibre db."""
    con = sqlite3.connect(input_calibre_db)
    cur = con.cursor()

    result = []
    for query_result in cur.execute(
        f"SELECT `annot_data` FROM `annotations` WHERE `book` = '{book_id}' and `user_type` = 'local'",
    ):
        annot_data = json.loads(query_result[0])

        if annot_data.get("removed", False):
            continue
        if annot_data.get("type") != "highlight":
            continue

        highlight = CalibreSourceHighlight(
            annot_data["start_cfi"],
            annot_data["end_cfi"],
            annot_data["spine_name"],
            annot_data["highlighted_text"],
            annot_data.get("style", {}).get("which", "yellow"),
        )
        result.append(highlight)

    con.close()
    return result


def get_distinct_highlights_from_calibre(
    input_calibre_db: pathlib.Path,
) -> Dict[int, List[CalibreSourceHighlight]]:
    """Get distinct highlights from the calibre db."""
    con = sqlite3.connect(input_calibre_db)
    cur = con.cursor()

    result = {}
    for query_result in cur.execute(
        f"SELECT `annot_data`, `book` FROM `annotations` WHERE `user_type` = 'local'",
    ):
        annot_data = json.loads(query_result[0])
        book = query_result[1]

        if annot_data.get("removed", False):
            continue
        if annot_data.get("type") != "highlight":
            continue

        highlight = CalibreSourceHighlight(
            annot_data.get("start_cfi"),
            annot_data.get("end_cfi"),
            annot_data.get("spine_name"),
            annot_data.get("highlighted_text"),
            annot_data.get("style", {}).get("which", "yellow"),
        )
        result.setdefault(book, []).append(highlight)

    con.close()
    return result


def get_highlights_from_kobo_by_book(
    input_kobo_db: pathlib.Path, book: str
) -> List[KoboSourceHighlight]:
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

        highlight = KoboSourceHighlight(
            row[3], row[6], row[5], row[8], row[9], content_path, row[24]
        )
        result.append(highlight)

    con.close()
    return result


def insert_highlights_into_calibre(
    output_calibre_db: pathlib.Path, books_highlights: List[CalibreTargetHighlight]
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

    logger.info(
        f"Inserted {actually_inserted_count} new highlights from Kobo into Calibre"
    )

    con.commit()
    con.close()
    return actually_inserted_count


def insert_highlights_into_kobo(
    output_kobo_db: pathlib.Path, highlights: List[KoboTargetHighlight]
) -> int:
    """Insert highlights into the kobo db."""
    con = sqlite3.connect(output_kobo_db)
    cur = con.cursor()

    logger.debug(f"Inserting {len(highlights)} highlights into Kobo")

    actually_inserted_count = 0
    for h in highlights:

        if cur.execute(
            f"SELECT `BookmarkID` from `Bookmark` where `BookmarkID` = '{h.uuid}'"
        ).fetchone():
            logger.debug(
                f"Annotation with id {h.uuid} (from {h.volume_id}) already exists in db"
            )
            continue

        query = (
            "INSERT INTO `Bookmark` ("
            "`VolumeID`, `ContentID`, `Text`, `StartContainerPath`, "
            "`EndContainerPath`, `StartOffset`, `EndOffset`, `BookmarkID`, "
            "`Color`, `StartContainerChildIndex`, `EndContainerChildIndex`, `Hidden`,"
            "`DateCreated`, `DateModified`, `Type`)"
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        cur.execute(
            query,
            (
                h.volume_id,
                h.content_id,
                h.text,
                h.start_path,
                h.end_path,
                h.start_offset,
                h.end_offset,
                h.uuid,
                h.color,
                -99,
                -99,
                "false",
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                "highlight",
            ),
        )

        actually_inserted_count += 1

    logger.info(
        f"Inserted {actually_inserted_count} new highlights from Calibre into Kobo"
    )

    con.commit()
    con.close()
    return actually_inserted_count
