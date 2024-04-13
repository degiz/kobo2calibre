import argparse
from typing import Any, Optional
import logging
import pathlib

try:
    # For calibre gui plugin
    from calibre_plugins.kobo2calibre import (
        converter,
    )  # pyright: reportMissingImports=false
    from calibre_plugins.kobo2calibre import db  # pyright: reportMissingImports=false
except ImportError:
    # For cli
    import converter  # type: ignore
    import db  # type: ignore


logger = logging.getLogger(__name__)


def configure_file_logging(args: Optional[Any]) -> None:
    """Configure logging to file."""
    formatter = logging.Formatter("[%(levelname)-5.5s][%(name)s] %(message)s")
    stream_handler = logging.StreamHandler()
    if not args or args.debug:
        stream_handler.setLevel(logging.DEBUG)
    else:
        stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logging.basicConfig(level=logging.DEBUG, handlers=[stream_handler])


def main(args) -> None:
    """Run the CLI program."""
    configure_file_logging(args)

    calibre_db = pathlib.Path(args.calibre_library).resolve() / "metadata.db"
    kobo_db = pathlib.Path(args.kobo_volume).resolve() / ".kobo" / "KoboReader.sqlite"

    to_insert = []
    for volume, highlights in db.get_dictinct_highlights_from_kobo(kobo_db).items():

        likely_book_id, likely_book_path = db.get_likely_book_path_from_calibre(
            calibre_db, pathlib.Path(args.kobo_volume), volume
        )
        if not likely_book_path:
            logger.debug(f"Failed to match book and skipping it: {volume}")
            continue

        if args.filter_bookname and args.filter_bookname not in volume:
            continue

        logger.debug(f"Processing book: {volume}")

        book_calibre_path = pathlib.Path(args.calibre_library) / pathlib.Path(
            likely_book_path
        )
        book_calibre_epub = [b for b in book_calibre_path.glob("*.epub")][0]

        to_insert.extend(
            converter.process_calibre_epub(
                book_calibre_epub, likely_book_id, highlights
            )
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
    parser.add_argument(
        "--filter_bookname",
        type=str,
        help="Filter only books matching a filter",
        required=False,
    )
    parser.add_argument("--debug", "-vv", action="store_true")
    args = parser.parse_args()
    main(args)
