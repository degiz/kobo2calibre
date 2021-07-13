import json
import logging
import pathlib
from typing import Dict, Tuple

import bs4


logger = logging.getLogger(__name__)


def get_calibre_book_id(kobo_volume: pathlib.Path, lpath: str) -> int:
    calibre_device_metadata = kobo_volume.resolve() / "metadata.calibre"
    with open(calibre_device_metadata) as f:
        metadata = json.load(f)
        target_book = list(
            filter(lambda x: x.get("lpath").split("/")[-1] == lpath, metadata)
        )[0]
        return target_book["application_id"]


def get_spine_index_map(
    root_dir: pathlib.Path,
) -> Tuple[Dict[str, int], Dict[str, str]]:
    content_file = [f for f in root_dir.rglob("content.opf")][0]
    with open(str(content_file)) as f:
        soup = bs4.BeautifulSoup(f.read(), "html.parser")

        # Read spine
        spine_ids = [
            s["idref"]
            for s in soup.package.spine.children
            if type(s) == bs4.element.Tag
        ]
        spine_index = {idref: i for i, idref in enumerate(spine_ids)}

        # Read manifest
        hrefs = [
            s
            for s in soup.package.manifest
            if type(s) == bs4.element.Tag and "application/xhtml" in s["media-type"]
        ]
        result = {}
        fixed_paths = {}
        for h in hrefs:
            final_href = h["href"]
            if not pathlib.Path(root_dir / final_href).exists():
                path = [r for r in root_dir.rglob(f"{h['href'].split('/')[-1]}")][0]
                final_href = str(path.relative_to(root_dir))
                fixed_paths[h["href"]] = final_href
            result[final_href] = spine_index[h["id"]]

        return result, fixed_paths
