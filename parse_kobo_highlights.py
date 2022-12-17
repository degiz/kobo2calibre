import argparse
import logging
import pathlib
import tempfile
import zipfile

import calibre
import converter
import db

logger = logging.getLogger(__name__)


def configure_file_logging(args) -> None:
    formatter = logging.Formatter("[%(levelname)-5.5s][%(name)s] %(message)s")
    stream_handler = logging.StreamHandler()
    if args.debug:
        stream_handler.setLevel(logging.DEBUG)
    else:
        stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logging.basicConfig(level=logging.DEBUG, handlers=[stream_handler])


def main(args) -> None:
    configure_file_logging(args)

    calibre_db = pathlib.Path(args.calibre_library).resolve() / "metadata.db"
    kobo_db = pathlib.Path(args.kobo_volume).resolve() / ".kobo/KoboReader.sqlite"

    to_insert = []
    for volume, highlights in db.get_dictinct_highlights_from_kobo(kobo_db).items():

        likely_book_id, likely_book_path = db.get_likely_book_path_from_calibre(
            calibre_db, pathlib.Path(args.kobo_volume), volume
        )
        if not likely_book_path:
            logger.debug(f"Failed to match book and skipping it: {volume}")
            continue

        logger.debug(f"Processing book: {volume}")

        book_calibre_path = pathlib.Path(args.calibre_library) / pathlib.Path(
            likely_book_path
        )
        book_calibre_epub = [b for b in book_calibre_path.glob("*.epub")][0]

        with tempfile.TemporaryDirectory() as tmpdirname:
            with zipfile.ZipFile(book_calibre_epub, "r") as zip_ref:
                zip_ref.extractall(tmpdirname)

                try:
                    spine_index_map, fixed_path = calibre.get_spine_index_map(
                        pathlib.Path(tmpdirname)
                    )

                    logger.debug(f"Spine index map: {spine_index_map}")

                    count = 0
                    for i, h in enumerate(highlights):
                        if h.content_path in fixed_path:
                            highlights[i] = highlights[i]._replace(
                                content_path=fixed_path[h.content_path]
                            )
                        calibre_highlight = converter.parse_kobo_highlights(
                            tmpdirname, h, likely_book_id, spine_index_map
                        )
                        if calibre_highlight:
                            to_insert.append(calibre_highlight)
                            logger.debug(f"Found highlight: {calibre_highlight}")
                            count += 1
                    logger.debug(f"..found {count} highlights")
                except Exception as e:
                    logger.error(
                        f"..failed to convert the highlights: {e} "
                        f"book: {book_calibre_epub}"
                    )

    db.insert_highlights_into_calibre(calibre_db, to_insert)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse Kobo highlights and save them to calibre database."
    )
    parser.add_argument("kobo_volume", type=str, help="Full path to the Kobo volume")
    parser.add_argument(
        "calibre_library",
        type=str,
        help="Full path to the Calibre library",
    )
    parser.add_argument("--debug", "-vv", action="store_true")
    args = parser.parse_args()
    main(args)
