import logging
import pathlib
import re
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import bs4
from bs4 import BeautifulSoup, NavigableString

try:
    # For calibre gui plugin
    from calibre_plugins.kobo2calibre import db  # pyright: reportMissingImports=false
except ImportError:
    # For cli
    import db  # type: ignore

logger = logging.getLogger(__name__)

# A regex that will most likely work on books converted with KTE plugin
REGEX_KTE = re.compile(
    r'(\s*.*?[\.\!\?\:][\'"\u201c\u201d\u2018\u2019\u2026]?\s*)',
    re.UNICODE | re.MULTILINE,
)


def get_spine_index_map(
    root_dir: pathlib.Path,
) -> Tuple[Dict[str, int], Dict[str, str]]:
    """Get the spine index map from the content.opf file."""
    content_file = [f for f in root_dir.rglob("*.opf")][0]
    with open(str(content_file)) as f:
        soup = bs4.BeautifulSoup(f.read(), "html.parser")

        # Read spine
        spine_ids = [
            s["idref"]
            for s in soup.package.spine.children
            if type(s) == bs4.element.Tag
        ]
        spine_index = {idref: i for i, idref in enumerate(spine_ids)}

        logger.debug(f"Spine index: {spine_index}")

        # Read manifest
        hrefs = [
            s
            for s in soup.package.manifest
            if type(s) == bs4.element.Tag
            and "application/xhtml" in s["media-type"]
            and (s["id"] in spine_ids)
        ]
        logger.debug(f"Found {len(hrefs)} hrefs")
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


def process_calibre_epub(
    book_calibre_epub: pathlib.Path, book_id: int, highlights: List[db.KoboHighlight]
) -> List[db.CalibreHighlight]:
    """Process a calibre epub file and return a list of highlights."""
    result = []
    with tempfile.TemporaryDirectory() as tmpdirname:
        with zipfile.ZipFile(book_calibre_epub, "r") as zip_ref:
            zip_ref.extractall(tmpdirname)

            try:
                spine_index_map, fixed_path = get_spine_index_map(
                    pathlib.Path(tmpdirname)
                )

                logger.debug(f"Spine index map: {spine_index_map}")

                count = 0
                for i, h in enumerate(highlights):

                    if h.content_path in fixed_path:
                        highlights[i] = highlights[i]._replace(
                            content_path=fixed_path[h.content_path]
                        )
                    calibre_highlight = parse_kobo_highlights(
                        tmpdirname, h, book_id, spine_index_map
                    )
                    if calibre_highlight:
                        result.append(calibre_highlight)
                        logger.debug(f"Found highlight: {calibre_highlight}")
                        count += 1
                logger.debug(f"..found {count} highlights")
            except Exception as e:
                logger.error(
                    f"..failed to convert the highlights: {e} "
                    f"book: {book_calibre_epub}"
                )
    return result


def get_prev_sentences_offset(node, n_sentences_offset) -> int:
    """Get the offset of the previous n sentences."""
    logger.debug(
        "Getting prev sentences offset, node: %s, offset: %d", node, n_sentences_offset
    )
    groups = REGEX_KTE.split(str(node))
    sentences = [g for g in groups if g != ""]

    logger.debug("Sentences: %s", sentences)

    prev_sentences_offset = 0
    if n_sentences_offset > 1:
        for i in range(0, n_sentences_offset - 1):
            prev_sentences_offset += len(sentences[i])
    return prev_sentences_offset


def encode_cfi(target_node, target_offset) -> str:
    """Encode a CFI for calibre."""
    logger.debug(
        "Encoding CFI, target_node: %s, target_offset: %s", target_node, target_offset
    )
    nodes = [p for p in target_node.parents][::-1]
    nodes.append(target_node)
    cfi = ""

    # encode all parents of the target node
    for node_id in range(0, len(nodes)):
        current_id = 2
        if nodes[node_id] == target_node:
            break
        children = [
            c for c in nodes[node_id].children if isinstance(c, bs4.element.Tag)
        ]
        for child_id in range(0, len(children)):
            if children[child_id] == nodes[node_id + 1]:
                cfi += f"/{current_id}"
                current_id = 2
                break
            current_id += 2

    # now encode the final node
    nodes = [p for p in target_node.parent.children]
    current_id = 1
    for node in nodes:
        if node == target_node:
            if isinstance(node, bs4.element.Tag):
                cfi += f"/{current_id}/1:{target_offset}"
            else:
                cfi += f"/{current_id}:{target_offset}"
            break
        current_id += 1

    return cfi


def parse_kobo_highlights(
    book_prefix, highlight, book_id, spine_index_map
) -> Optional[db.CalibreHighlight]:
    """Parse a kobo highlight and return a calibre highlight."""
    kobo_n_tag_start, kobo_n_sentence_start = [
        int(i) for i in highlight.start_path.split("\\.")[1:]
    ]
    kobo_n_tag_end, kobo_n_sentence_end = [
        int(i) for i in highlight.end_path.split("\\.")[1:]
    ]
    logger.debug(
        f"parsing highlight: {highlight.start_path}, "
        f"{highlight.end_path}, {highlight.content_path}"
    )
    logger.debug(f"Text: {highlight.text}")

    input_filename = pathlib.Path(book_prefix) / pathlib.Path(highlight.content_path)

    # That's a dirty hack
    if not pathlib.Path(input_filename).is_file():
        highlight = highlight._replace(
            content_path=highlight.content_path.replace("/", "!")
        )
        input_filename = pathlib.Path(book_prefix) / pathlib.Path(
            highlight.content_path
        )

    with open(input_filename) as f:
        soup = BeautifulSoup(f.read(), "html.parser")

        # First find the node using KOBO notation
        target_start_node = None
        target_end_node = None
        kobo_target_start_offset = highlight.start_offset
        kobo_target_end_offset = highlight.end_offset
        intermidiate_offset = 0
        do_append = False
        n_tag = 1

        first_parent = soup.body

        for child in first_parent.descendants:
            parent_names = [p.name for p in child.parents]
            if "figure" in parent_names:
                continue

            if (
                not isinstance(child, bs4.element.NavigableString)
                or isinstance(child, bs4.element.Comment)
                or str(child) == "\n"
                or str(child) == " "
                or str(child) == "\u00A0"  # non-breaking space, used in the tables
                or str(child).strip() == ""
            ):
                continue

            logger.debug(f"Including tag #{n_tag}: {child}")

            if n_tag == kobo_n_tag_start:
                target_start_node = (str(child), child)
                child_length = len(str(child))

                # Add lengths of previous sentences
                kobo_target_start_offset += get_prev_sentences_offset(
                    child, kobo_n_sentence_start
                )

                if kobo_n_tag_start == kobo_n_tag_end:
                    target_end_node = target_start_node
                    if kobo_n_sentence_start == kobo_n_sentence_end:
                        kobo_target_end_offset += (
                            kobo_target_start_offset - highlight.start_offset
                        )
                    else:
                        kobo_target_end_offset += get_prev_sentences_offset(
                            child, kobo_n_sentence_end
                        )
                    break
                else:
                    do_append = True
                    intermidiate_offset += child_length

            elif n_tag == kobo_n_tag_end:
                target_end_node = (str(child), child)
                kobo_target_end_offset += get_prev_sentences_offset(
                    child, kobo_n_sentence_end
                )
                break

            elif do_append:
                intermidiate_offset += len(str(child))

            n_tag += 1

        if not target_start_node:
            logger.debug("Failed to find the target start node")
            return None
        if not target_end_node:
            logger.debug("Failed to find the target end node")
            return None

        start_cfi = encode_cfi(target_start_node[1], kobo_target_start_offset)
        end_cfi = encode_cfi(target_end_node[1], kobo_target_end_offset)

        unique_uuid = str(
            uuid.uuid3(
                uuid.NAMESPACE_DNS, f"{start_cfi}*{end_cfi}*{highlight.text})"
            ).hex
        )

        calibre_highlight_json = {
            "start_cfi": start_cfi,
            "end_cfi": end_cfi,
            "highlighted_text": highlight.text,
            "spine_index": spine_index_map[highlight.content_path],
            "spine_name": highlight.content_path,
            "style": {"kind": "color", "type": "builtin", "which": "green"},
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "highlight",
            "uuid": unique_uuid,
        }

        calibre_highlight = db.CalibreHighlight(
            book_id,
            "EPUB",
            "local",
            "viewer",
            int(time.time()),
            unique_uuid,
            "highlight",
            calibre_highlight_json,
            highlight.text,
        )
        return calibre_highlight


def decode_calibre_cfi(
    soup: BeautifulSoup, cfi: str
) -> (bs4.element.NavigableString, int):
    """
    Decodes a Calibre CFI string and returns the target NavigableString and its character offset.

    The Calibre CFI format is expected to have slash-separated segments.
    The intermediate segments (e.g. /2/4/2[id1]/4) are encoded using even numbers.
    The final segment is of the form '/<node_index>:<offset>', where node_index is counted among
    all children (including non-tags), starting at 1.
    """

    parts = cfi.strip().split("/")
    if len(parts) < 2:
        raise ValueError("Invalid CFI string")

    current_node = soup.html
    # Process all intermediate segments (ignoring the final one)
    # We start from "2", because above we already set current_node to soup.html
    for part in parts[2:-1]:
        # Remove any square-bracket annotation (e.g. [id1])
        m = re.match(r"(\d+)", part)
        if not m:
            raise ValueError(f"Invalid segment in CFI: '{part}'")
        num = int(m.group(1))
        # In the encoding for parents an even number was used.
        # The Calibre algorithm started counting at 2 and incremented by 2.
        # To invert that, we subtract 2 then divide by 2.
        child_index = (num // 2) - 1
        # Only consider Tag children (as in the original encode)
        children = [
            child
            for child in current_node.children
            if isinstance(child, bs4.element.Tag)
        ]

        print(
            f"Processing segment '{part}': current_node={current_node.name}, children_count={len(children)}, child_index={child_index}"
        )

        if child_index < 0 or child_index >= len(children):
            raise IndexError("Child index out of bounds while decoding CFI")
        current_node = children[child_index]

    children = [
        child for child in current_node.children if isinstance(child, bs4.element.Tag)
    ]
    print(f"current_node={current_node.name}, children_count={len(children)}")

    # Process final segment, expected format: e.g. "1:78"
    final_segment = parts[-1]
    m = re.match(r"(\d+):(\d+)", final_segment)
    if not m:
        raise ValueError("Invalid final segment in CFI: " + final_segment)
    sibling_number = int(m.group(1))
    offset = int(m.group(2))
    # For the final segment, we use the parent’s full list of children (including strings)
    siblings = list(current_node.children)
    if sibling_number < 1 or sibling_number > len(siblings):
        raise IndexError("Sibling index out of bounds in final segment")
    target_node = siblings[sibling_number - 1]
    if not isinstance(target_node, bs4.element.NavigableString):
        raise ValueError("Target node is not a text node")
    return target_node, offset


def convert_calibre_cfi_to_kobo(soup: BeautifulSoup, cfi: str) -> (str, int):
    """
    Converts a Calibre CFI to a Kobo reader CFI.

    Returns a tuple:
      (kobo_path, kobo_offset)
    where:
      kobo_path: a string of the form "span#kobo\.{n_tag}\.{n_sentence}"
      kobo_offset: the character offset within the given sentence.
    """
    # Decode the Calibre CFI first to obtain the target text node and overall offset
    target_node, overall_offset = decode_calibre_cfi(soup, cfi)

    # Traverse the document to get the Kobo text node index.
    # This simulates the original Kobo conversion where only non-empty text nodes (ignoring whitespace,
    # newlines, &#160; etc.) are counted.
    n_tag = 1
    found = False
    # For Kobo, we start with the body tag right away
    for child in soup.body.descendants:
        # Skip non-text nodes, comments, or nodes with only whitespace.
        if not isinstance(child, bs4.element.NavigableString) or isinstance(
            child, bs4.element.Comment
        ):
            continue
        text = str(child)
        if text in ("\n", " ", "\u00A0") or text.strip() == "":
            continue
        # You may want to further exclude nodes that are within a <figure> (as in your original code)
        parent_names = [p.name for p in child.parents if isinstance(p, bs4.element.Tag)]
        if "figure" in parent_names:
            continue

        if child == target_node:
            found = True
            break
        n_tag += 1

    if not found:
        raise ValueError("Target text node not found among the valid text nodes")

    # Now, using the text content, split it into sentences.
    # The logic here mimics your get_prev_sentences_offset: it traverses the list
    # of sentences until the cumulative length exceeds overall_offset.
    sentences = [seg for seg in REGEX_KTE.split(str(target_node)) if seg != ""]
    cumulative = 0
    kobo_sentence = 1
    kobo_offset = 0
    for sentence in sentences:
        if cumulative + len(sentence) > overall_offset:
            kobo_offset = overall_offset - cumulative
            break
        cumulative += len(sentence)
        kobo_sentence += 1
    else:
        # In case the overall_offset is greater than the total length
        kobo_offset = overall_offset - cumulative

    # Construct the Kobo path.
    # The standard format (as derived from your original Kobo example) is:
    #   "span#kobo\.{n_tag}\.{n_sentence}"
    # Use double escapes for the dots.
    kobo_path = f"span#kobo\\.{n_tag}\\.{kobo_sentence}"

    return kobo_path, kobo_offset


# Example usage:
if __name__ == "__main__":

    with open("/Users/degiz/Desktop/epub/OPS/ch1-6.xhtml", "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # Example Calibre CFI values taken from your example:
    calibre_start_cfi = "/2/4/2/2/4/1:2315"
    calibre_end_cfi = "/2/4/2/2/4/1:2408"

    # Convert the Calibre start CFI to Kobo format
    kobo_start_path, kobo_start_offset = convert_calibre_cfi_to_kobo(
        soup, calibre_start_cfi
    )
    print("Kobo Start CFI:")
    print("Path:", kobo_start_path)
    print("Offset:", kobo_start_offset)

    # Convert the Calibre end CFI to Kobo format
    kobo_end_path, kobo_end_offset = convert_calibre_cfi_to_kobo(soup, calibre_end_cfi)
    print("\nKobo End CFI:")
    print("Path:", kobo_end_path)
    print("Offset:", kobo_end_offset)
