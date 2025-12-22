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
from bs4 import BeautifulSoup

from db import KoboTargetHighlight

try:
    # For calibre gui plugin
    from calibre_plugins.kobo2calibre import db  # pyright: reportMissingImports=false
except ImportError:
    # For cli
    import db  # type: ignore

# Try to import calibre's kepubify (available when running via calibre-debug)
try:
    from calibre.ebooks.oeb.polish.kepubify import (
        kepubify_html_data,
        Options as KepubifyOptions,
    )
    from calibre.spell.break_iterator import sentence_positions

    HAS_KEPUBIFY = True
except ImportError:
    sentence_positions = None  # type: ignore
    HAS_KEPUBIFY = False

logger = logging.getLogger(__name__)

# Fallback regex for CLI mode (when calibre's sentence_positions is not available)
REGEX_KTE = re.compile(
    r'(\s*.*?[\.\!\?\:][\'"\u201c\u201d\u2018\u2019\u2026]?\s*)',
    re.UNICODE | re.MULTILINE,
)

# Block tags that increment the paragraph counter in Kobo's numbering scheme
BLOCK_TAGS = frozenset(("p", "ol", "ul", "table", "h1", "h2", "h3", "h4", "h5", "h6"))


def split_into_sentences(text: str, lang: str = "en") -> List[str]:
    """Split text into sentences using Calibre's ICU-based splitter when available."""
    if sentence_positions is not None:
        sentences = []
        for pos, sz in sentence_positions(text, lang):
            sentences.append(text[pos : pos + sz])
        return sentences
    else:
        # Fallback to regex for CLI mode
        groups = REGEX_KTE.split(text)
        return [g for g in groups if g != ""]


def get_block_offset_from_kepubify(raw_html: bytes, block_num: int, sentence_num: int) -> Optional[int]:
    """
    Use Calibre's kepubify to find the character offset from the start of a block
    to the start of a specific sentence.

    Returns the offset, or None if the span is not found.
    """
    if not HAS_KEPUBIFY:
        logger.warning("Kepubify not available")
        return None

    root = kepubify_html_data(raw_html, opts=KepubifyOptions())

    # Sum text lengths of all spans before the target sentence in this block
    offset = 0
    for sent in range(1, sentence_num):
        span_id = f"kobo.{block_num}.{sent}"
        spans = root.xpath(f'//*[@id="{span_id}"]')
        if spans:
            span_text = spans[0].text or ""
            offset += len(span_text)
            logger.debug(f"Span {span_id}: len={len(span_text)}, cumulative offset={offset}")

    # Verify the target span exists
    target_span_id = f"kobo.{block_num}.{sentence_num}"
    target_spans = root.xpath(f'//*[@id="{target_span_id}"]')
    if not target_spans:
        logger.warning(f"Span {target_span_id} not found in kepubified HTML")
        return None

    logger.debug(f"Found span {target_span_id}, offset from block start: {offset}")
    return offset


def find_text_node_at_block_offset(
    soup: BeautifulSoup, target_block: int, char_offset: int
) -> Optional[Tuple[bs4.element.NavigableString, int]]:
    """
    Find the text node in the original document that contains the character
    at the given offset within the specified block.

    Returns (text_node, offset_within_node) or None.
    """
    # Find the Nth block element
    block_num = 0
    target_element = None

    for elem in soup.body.descendants:
        if isinstance(elem, bs4.element.Tag):
            tagname = elem.name.lower() if elem.name else ""
            if tagname in BLOCK_TAGS:
                block_num += 1
                if block_num == target_block:
                    target_element = elem
                    break

    if target_element is None:
        logger.warning(f"Block {target_block} not found in document")
        return None

    # Now find the text node containing the character at char_offset
    # by iterating through all text descendants of this block
    cumulative_offset = 0
    for node in target_element.descendants:
        if not isinstance(node, bs4.element.NavigableString):
            continue
        if isinstance(node, bs4.element.Comment):
            continue

        text = str(node)
        node_len = len(text)

        if cumulative_offset + node_len >= char_offset:
            # This node contains our target character
            offset_in_node = char_offset - cumulative_offset
            logger.debug(
                f"Found text node at offset {char_offset}: "
                f"node_offset={offset_in_node}, text={repr(text[:50])}"
            )
            return (node, offset_in_node)

        cumulative_offset += node_len

    logger.warning(
        f"Offset {char_offset} not found in block {target_block} "
        f"(block has {cumulative_offset} chars)"
    )
    return None


def get_spine_index_map(
    root_dir: pathlib.Path,
) -> Tuple[Dict[str, int], Dict[str, str], str]:
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

        p = str(pathlib.Path(content_file).relative_to(root_dir))
        logger.debug(f"relative path: {p}")

        return (
            result,
            fixed_paths,
            str(pathlib.Path(content_file).relative_to(root_dir)),
        )


def process_calibre_epub_from_kobo(
    book_calibre_epub: pathlib.Path,
    book_id: int,
    highlights: List[db.KoboSourceHighlight],
    kepub_format: str = "new",
) -> List[db.CalibreTargetHighlight]:
    """Process a calibre epub file and return a list of highlights."""
    result = []
    with tempfile.TemporaryDirectory() as tmpdirname:
        with zipfile.ZipFile(book_calibre_epub, "r") as zip_ref:
            zip_ref.extractall(tmpdirname)

            try:
                spine_index_map, fixed_path, _ = get_spine_index_map(
                    pathlib.Path(tmpdirname)
                )

                logger.debug(f"Spine index map: {spine_index_map}")

                count = 0
                for i, h in enumerate(highlights):

                    if h.content_path in fixed_path:
                        highlights[i] = highlights[i]._replace(
                            content_path=fixed_path[h.content_path]
                        )
                    calibre_target_highlight = parse_kobo_highlights(
                        tmpdirname, h, book_id, spine_index_map, kepub_format
                    )
                    if calibre_target_highlight:
                        result.append(calibre_target_highlight)
                        logger.debug(f"Found highlight: {calibre_target_highlight}")
                        count += 1
                logger.debug(f"..found {count} highlights")
            except Exception as e:
                logger.error(
                    f"..failed to convert the highlights: {e} "
                    f"book: {book_calibre_epub}"
                )
    return result


def process_calibre_epub_from_calibre(
    book_calibre_epub: pathlib.Path,
    kobo_lpath: str,
    highlights: List[db.CalibreSourceHighlight],
):
    """Process a calibre epub file and return a list of highlights."""
    result = []
    with tempfile.TemporaryDirectory() as tmpdirname:
        with zipfile.ZipFile(book_calibre_epub, "r") as zip_ref:
            zip_ref.extractall(tmpdirname)

            _, _, content_file = get_spine_index_map(pathlib.Path(tmpdirname))
            slash_count = content_file.count("/")

            for h in highlights:
                logger.debug(f"Processing spine: {h.spine_name}")
                if not h.spine_name:
                    logger.debug(
                        f"Skipping highlight without spine: {h.highlighted_text}"
                    )
                soup = BeautifulSoup(
                    open(pathlib.Path(tmpdirname) / pathlib.Path(h.spine_name)),
                    "html.parser",
                )

                # Get text of <h1> tag
                text = soup.h1.get_text() if soup.h1 else ""

                kobo_start_path, kobo_start_offset = convert_calibre_cfi_to_kobo(
                    soup, h.start_cfi
                )
                kobo_end_path, kobo_end_offset = convert_calibre_cfi_to_kobo(
                    soup, h.end_cfi
                )
                logger.debug(f"Calibre CFI: {h.start_cfi}, {h.end_cfi}")
                logger.debug(
                    f"Kobo CFI: {kobo_start_path}, offset: {kobo_start_offset}, {kobo_end_path}, offset: {kobo_end_offset}"
                )
                logger.debug(f"Text: {h.highlighted_text}")

                unique_uuid = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"{h.start_cfi}*{h.end_cfi}*{h.highlighted_text})",
                    ).hex
                )

                if slash_count > 0:
                    adapted_spinename = h.spine_name.replace("/", "!", slash_count)
                else:
                    adapted_spinename = f"!{h.spine_name}"

                kobo_highlight = KoboTargetHighlight(
                    kobo_start_path,
                    kobo_end_path,
                    kobo_start_offset,
                    kobo_end_offset,
                    h.highlighted_text,
                    f"file:///mnt/onboard/{kobo_lpath}",
                    f"/mnt/onboard/{kobo_lpath}!{adapted_spinename}",
                    calibre_color_to_kobo_color(h.color),
                    unique_uuid,
                )
                result.append(kobo_highlight)

    return result


def calibre_color_to_kobo_color(color: str) -> int:
    """Convert a calibre color to a kobo color."""
    if color == "green":
        return 3
    if color == "yellow":
        return 0
    if color == "blue":
        return 2
    if color == "purple":
        return 1
    return 0


def kobo_color_to_calibre_color(color: int) -> str:
    """Convert a kobo color to a calibre color."""
    if color == 3:
        return "green"
    if color == 0:
        return "yellow"
    if color == 2:
        return "blue"
    if color == 1:
        return "purple"
    return "yellow"


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


def is_new_kepub_format(kepub_format: str) -> bool:
    """Check if the kepub format is new (Calibre kepubify) or old (KTE plugin).

    Args:
        kepub_format: Either 'new' or 'old'

    Returns:
        True if using new format (Calibre kepubify), False if using old format (KTE plugin)
    """
    return kepub_format == "new"


def find_text_by_kte_path(
    soup: BeautifulSoup, target_tag: int, target_sentence: int, lang: str = "en"
) -> Optional[Tuple[bs4.element.NavigableString, int]]:
    """
    Find text node using old KTE plugin's text-node counting scheme.

    KTE numbered text nodes sequentially (not by blocks), and split sentences with regex.
    Returns (text_node, char_offset_to_start_of_sentence) or None if not found.
    """
    n_tag = 1

    for child in soup.body.descendants:
        parent_names = [p.name for p in child.parents]
        if "figure" in parent_names:
            continue

        if (
            not isinstance(child, bs4.element.NavigableString)
            or isinstance(child, bs4.element.Comment)
            or str(child) == "\n"
            or str(child) == " "
            or str(child) == "\u00a0"
            or str(child).strip() == ""
        ):
            continue

        logger.debug(f"KTE tag #{n_tag}: {repr(str(child)[:50])}...")

        if n_tag == target_tag:
            # Found the right text node, now find the sentence
            sentences = split_into_sentences(str(child), lang)
            if target_sentence <= len(sentences):
                offset = sum(len(s) for s in sentences[: target_sentence - 1])
                return (child, offset)
            else:
                logger.warning(
                    f"Sentence {target_sentence} not found in tag {target_tag} "
                    f"(only {len(sentences)} sentences)"
                )
                return None

        n_tag += 1

    logger.warning(f"KTE tag {target_tag} not found (max was {n_tag - 1})")
    return None


def parse_kobo_highlights(
    book_prefix, highlight, book_id, spine_index_map, kepub_format: str = "new"
) -> Optional[db.CalibreTargetHighlight]:
    """Parse a kobo highlight and return a calibre highlight."""
    kobo_n_start, kobo_n_sentence_start = [
        int(i) for i in highlight.start_path.split("\\.")[1:]
    ]
    kobo_n_end, kobo_n_sentence_end = [
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

    with open(input_filename, "rb") as f:
        raw_html = f.read()

    # For chapter title, we still need BeautifulSoup
    soup = BeautifulSoup(raw_html, "html.parser")
    chapter_title = guess_chapter_title(soup)

    use_new_format = is_new_kepub_format(kepub_format)

    if use_new_format and HAS_KEPUBIFY:
        # Use Calibre's kepubify to calculate offsets, then find in original doc
        logger.debug("Using Calibre's kepubify for offset calculation")

        # Get offset from block start to sentence start
        start_sentence_offset = get_block_offset_from_kepubify(
            raw_html, kobo_n_start, kobo_n_sentence_start
        )
        if start_sentence_offset is None:
            logger.debug("Failed to find the start sentence offset")
            return None

        # Total offset = offset to sentence + offset within sentence
        start_total_offset = start_sentence_offset + highlight.start_offset
        logger.debug(f"Start: block={kobo_n_start}, sentence_offset={start_sentence_offset}, "
                     f"highlight_offset={highlight.start_offset}, total={start_total_offset}")

        # Find the text node in the original document
        # Note: kepubify block N corresponds to original document block N-1
        # because kepubify consumes block 1 for whitespace at document start
        original_block_start = kobo_n_start - 1
        start_result = find_text_node_at_block_offset(soup, original_block_start, start_total_offset)
        if not start_result:
            logger.debug("Failed to find start text node in original document")
            return None
        target_start_node, start_offset_in_node = start_result

        # Handle end offset
        original_block_end = kobo_n_end - 1
        if kobo_n_start == kobo_n_end and kobo_n_sentence_start == kobo_n_sentence_end:
            # Same sentence - just different offset
            end_total_offset = start_sentence_offset + highlight.end_offset
            end_result = find_text_node_at_block_offset(soup, original_block_end, end_total_offset)
        else:
            # Different sentence
            end_sentence_offset = get_block_offset_from_kepubify(
                raw_html, kobo_n_end, kobo_n_sentence_end
            )
            if end_sentence_offset is None:
                logger.debug("Failed to find the end sentence offset")
                return None
            end_total_offset = end_sentence_offset + highlight.end_offset
            end_result = find_text_node_at_block_offset(soup, original_block_end, end_total_offset)

        if not end_result:
            logger.debug("Failed to find end text node in original document")
            return None
        target_end_node, end_offset_in_node = end_result

        # Generate CFI using the original document structure
        start_cfi = encode_cfi(target_start_node, start_offset_in_node)
        end_cfi = encode_cfi(target_end_node, end_offset_in_node)
    else:
        # Fallback for old KTE format or when kepubify unavailable
        logger.debug(f"Using {'old KTE' if not use_new_format else 'fallback'} format")

        start_result = find_text_by_kte_path(soup, kobo_n_start, kobo_n_sentence_start)
        if not start_result:
            logger.debug("Failed to find the target start node")
            return None

        target_start_node, sentence_start_offset = start_result
        kobo_target_start_offset = sentence_start_offset + highlight.start_offset

        if kobo_n_start == kobo_n_end:
            target_end_node = target_start_node
            if kobo_n_sentence_start == kobo_n_sentence_end:
                kobo_target_end_offset = sentence_start_offset + highlight.end_offset
            else:
                end_result = find_text_by_kte_path(soup, kobo_n_end, kobo_n_sentence_end)
                if not end_result:
                    logger.debug("Failed to find the target end node")
                    return None
                _, sentence_end_offset = end_result
                kobo_target_end_offset = sentence_end_offset + highlight.end_offset
        else:
            end_result = find_text_by_kte_path(soup, kobo_n_end, kobo_n_sentence_end)
            if not end_result:
                logger.debug("Failed to find the target end node")
                return None
            target_end_node, sentence_end_offset = end_result
            kobo_target_end_offset = sentence_end_offset + highlight.end_offset

        start_cfi = encode_cfi(target_start_node, kobo_target_start_offset)
        end_cfi = encode_cfi(target_end_node, kobo_target_end_offset)

    # Common code for both branches
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
        "style": {
            "kind": "color",
            "type": "builtin",
            "which": kobo_color_to_calibre_color(highlight.color),
        },
        "toc_family_titles": [chapter_title],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "highlight",
        "uuid": unique_uuid,
    }

    calibre_highlight = db.CalibreTargetHighlight(
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

        logger.debug(
            f"Processing segment '{part}': current_node={current_node.name}, children_count={len(children)}, child_index={child_index}"
        )

        if child_index < 0 or child_index >= len(children):
            raise IndexError("Child index out of bounds while decoding CFI")
        current_node = children[child_index]

    children = [
        child for child in current_node.children if isinstance(child, bs4.element.Tag)
    ]
    logger.debug(f"current_node={current_node.name}, children_count={len(children)}")

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
    r"""
    Converts a Calibre CFI to a Kobo reader CFI.

    Returns a tuple:
      (kobo_path, kobo_offset)
    where:
      kobo_path: a string of the form "span#kobo\.{n_block}\.{n_sentence}"
      kobo_offset: the character offset within the given sentence.
    """
    # Decode the Calibre CFI first to obtain the target text node and overall offset
    target_node, overall_offset = decode_calibre_cfi(soup, cfi)

    # Traverse the document using Kobo's block-based numbering scheme
    # Calibre kepubify starts paranum at 0, increments before first text
    paranum = 0
    increment_next_para = True
    found = False

    for element in soup.body.descendants:
        # Check if this is a block tag - set flag to increment paranum on next text
        if isinstance(element, bs4.element.Tag):
            tagname = element.name.lower() if element.name else ""
            if tagname in BLOCK_TAGS and not increment_next_para:
                increment_next_para = True
            continue

        # Skip non-text nodes
        if not isinstance(element, bs4.element.NavigableString):
            continue
        if isinstance(element, bs4.element.Comment):
            continue

        text = str(element)
        # Skip whitespace-only text
        if text in ("\n", " ", "\u00a0") or text.strip() == "":
            continue

        # Skip text inside figure elements
        parent_names = [p.name for p in element.parents if hasattr(p, "name")]
        if "figure" in parent_names:
            continue

        # Increment paragraph counter if we're starting a new block
        if increment_next_para:
            paranum += 1
            increment_next_para = False

        if element == target_node:
            found = True
            break

    if not found:
        raise ValueError("Target text node not found among the valid text nodes")

    # Now, using the text content, split it into sentences.
    # Find which sentence the offset falls in.
    sentences = split_into_sentences(str(target_node))
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
    # The standard format is: "span#kobo\.{n_block}\.{n_sentence}"
    kobo_path = f"span#kobo\\.{paranum}\\.{kobo_sentence}"

    return kobo_path, kobo_offset


def guess_chapter_title(soup):

    # 2. Look for <h1> as it's common for chapter headings
    h1 = soup.find("h1")
    if h1 and h1.get_text():
        h1_text = h1.get_text().strip()
        if h1_text:
            return h1_text

    # 3. Look for <h2>, sometimes chapters are marked with h2
    h2 = soup.find("h2")
    if h2 and h2.get_text():
        h2_text = h2.get_text().strip()
        if h2_text:
            return h2_text

    # 4. As a fallback, try to see if there's a div with a class indicating chapter title
    possible_titles = soup.find_all("div", class_="chapter-title")
    for div in possible_titles:
        text = div.get_text().strip()
        if text:
            return text

    # If no title is guessed, return a default notice
    return "Chapter title not found."
