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
from bs4 import BeautifulSoup, NavigableString, Tag, Comment, ProcessingInstruction

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


# ------------------------------------------------------------------
# 1) Example function: parse a System 1 CFI into (path_list, char_offset).
#    E.g. '/1/4/1/1/2/106/1/1:12' -> ([1,4,1,1,2,106,1,1], 12)
# ------------------------------------------------------------------
def parse_system1_cfi(cfi_str):
    # Strip leading slash
    cfi_str = cfi_str.lstrip("/")

    # Split at the colon for offset
    if ":" in cfi_str:
        path_part, offset_str = cfi_str.split(":", 1)
        char_offset = int(offset_str)
    else:
        path_part = cfi_str
        char_offset = None

    # Split by '/' to get the path integers
    steps = [int(x) for x in path_part.split("/") if x]

    return steps, char_offset


# ------------------------------------------------------------------
# 2) Example function: find the text node (and confirm length) in the DOM,
#    using System 1's skipping/indexing logic.
#
#    NOTE: This is HIGHLY dependent on replicating exactly how System 1
#    enumerates children (e.g. skipping whitespace, ignoring certain nodes, etc.).
#    Below is just an illustrative approach.
# ------------------------------------------------------------------
def find_node_by_system1_path(soup, steps):
    """
    Walks the DOM according to a list of 1-based 'steps', returning the final node.

    - Skips only Comment and ProcessingInstruction nodes.
    - KEEPS all Tag and NavigableString (including whitespace).
    - If you have a path like [1,4,2,3,1], you won't get "out of range" unless
      the document truly lacks enough children at each level.
    """
    current = soup  # Start at <html> or [document] after parse_only_html_body

    for step in steps:
        # Make sure we can iterate .children on 'current'
        while current and not hasattr(current, "children"):
            current = current.parent
        if not current or not hasattr(current, "children"):
            raise ValueError(f"Encountered non-traversable node at step={step}.")

        # Collect children, skipping only comments and processing instructions
        significant_children = []
        for child in current.children:
            if isinstance(child, (Comment, ProcessingInstruction)):
                # skip
                continue
            # Keep Tag and NavigableString (including whitespace)
            significant_children.append(child)

        idx = step - 1  # convert 1-based step to 0-based
        if idx < 0 or idx >= len(significant_children):
            node_name = getattr(current, "name", "[document]")
            raise ValueError(
                f"Step {step} is out of range. Only {len(significant_children)} children under <{node_name}>."
            )

        current = significant_children[idx]

    return current


# ------------------------------------------------------------------
# 3) Example function: once we have the EXACT text node,
#    we generate a new path using System 2's logic.
# ------------------------------------------------------------------
def generate_system2_cfi_for_node(soup, node, offset):
    """
    Build a System 2 CFI path, e.g. "/2/4/2[id2]/6/1:0".

    Strategy:
      - Root = "/2" => (i.e., <html>).
      - We do NOT create steps for the [document] node.
      - We keep <head> (so it occupies a child index).
      - We keep ALL text nodes (including whitespace), only skipping Comments + ProcessingInstructions.
      - This way <body> can indeed be child #4, if the first 1..3 children of <html> are:
          1) text node, 2) <head>, 3) text node, 4) <body>
      - If the current Tag has an 'id' attribute, we encode that step as "childIndex[idValue]".
      - The final text node offset = ":0" or ":854" etc.
    """

    chain_reversed = []
    current = node

    while current and current is not soup:
        parent = current.parent
        if parent is None:
            break

        # If we've reached the [document], we treat <html> as the root => "/2" and stop.
        if getattr(parent, "name", None) == "[document]":
            chain_reversed.append("2")  # meaning <html> = /2
            break

        # Build parent's child list, skipping only Comments/ProcessingInstructions
        siblings = []
        for child in parent.children:
            if isinstance(child, (Comment, ProcessingInstruction)):
                continue
            # Keep text nodes (including whitespace), keep all tags (including <head>)
            siblings.append(child)

        # Find 1-based index of 'current' among these siblings
        idx_1_based = None
        for i, sib in enumerate(siblings, start=1):
            if sib == current:
                idx_1_based = i
                break

        if idx_1_based is None:
            raise ValueError(
                "Could not locate node among parent's children for System 2 indexing."
            )

        # If 'current' is a Tag with an 'id', embed it in brackets e.g. 2[id2]
        bracket_part = ""
        if isinstance(current, Tag) and current.has_attr("id"):
            bracket_part = f"[{current['id']}]"

        step_str = f"{idx_1_based}{bracket_part}"
        chain_reversed.append(step_str)

        current = parent

    # If we never appended "2" for <html> (meaning we didn't hit the [document] parent),
    # let's see if our parent is <html> itself:
    if len(chain_reversed) == 0:
        # The node's parent might literally be <html>, so let's just do /2
        chain_reversed.append("2")

    # Reverse so it’s top-down
    chain_system2 = list(reversed(chain_reversed))

    # Combine into a string
    path_part = "/".join(chain_system2)
    cfi_str = f"/{path_part}:{offset}"
    return cfi_str


def convert_offset_prog1_to_prog2(text_prog1: str, offset_prog1: int) -> int:
    """
    Convert a character offset in '\\uXXXX'-escaped text (program 1 format)
    to the corresponding offset in normal Unicode text (program 2 format).

    :param text_prog1: The string as stored by program 1 (e.g., '\\u041e\\u043d ...')
    :param offset_prog1: The 0-based offset in text_prog1, assumed to be on a character boundary.
    :return: The corresponding offset (0-based) in the decoded program 2 text.
    """

    # 1) Substring of the escaped text up to (not including) offset_prog1.
    #    That includes all the escape sequences/ASCII characters prior to the offset.
    decoded_text = text_prog1.encode("ascii").decode("unicode_escape")
    decoded_substring = decoded_text.encode("utf-8")
    substring_prog1 = decoded_substring[:offset_prog1]

    # it can be, that the last character is incompete unicode character like "\u0" oe "\u04" or "\u041" or "\u" or "\"
    # in this case we need to remove the last character

    # 2) Decode this substring from the backslash-unicode-escape representation.
    #    - encode('ascii') turns the Python str into raw bytes (ASCII).
    #    - decode('unicode_escape') interprets backslash-escapes like \u041e as Unicode chars.

    # 3) The length of the decoded_substring is how many actual Unicode (program 2) characters
    #    exist before offset_prog1 in the original \uXXXX text.
    offset_prog2 = len(substring_prog1.decode("utf-8"))

    return offset_prog2


# ------------------------------------------------------------------
# 4) Put it all together: a converter function
# ------------------------------------------------------------------
def convert_cfi_system1_to_system2(soup, cfi_str_system1):
    """
    html_content: string containing your HTML
    cfi_str_system1: e.g. '/1/4/1/1/2/106/1/1:12'
    returns: cfi_str_system2, e.g. '/2/4/2/110/1:12'
    """

    # Parse the system 1 CFI
    steps_system1, char_offset = parse_system1_cfi(cfi_str_system1)

    # Find the node in the DOM using system1's logic
    node = find_node_by_system1_path(soup, steps_system1)
    if not isinstance(node, NavigableString):
        raise ValueError("System1 path ended on an element, but expected a text node!")

    node_ascii_text = str(node).encode("unicode_escape").decode("ascii")
    char_offset_system2 = convert_offset_prog1_to_prog2(node_ascii_text, char_offset)

    # Generate the new CFI in system 2's logic
    # cfi_str_system2 = generate_system2_cfi_for_node(soup, node, char_offset)
    cfi_str_system2 = encode_cfi(node, char_offset_system2)

    return cfi_str_system2


def get_spine_index_map(
    root_dir: pathlib.Path,
) -> Tuple[Dict[str, int], Dict[str, str]]:
    """Get the spine index map from the content.opf file."""
    content_file = [f for f in root_dir.rglob("*.opf")][0]
    with open(str(content_file)) as f:
        # soup = bs4.BeautifulSoup(f.read(), "html.parser")

        soup_all = BeautifulSoup(f.read(), "html.parser")
        html_tag = soup_all.find("html")
        if html_tag:
            # Re-parse only the <html> ... </html> part.
            # That new soup will have <html> as its top-level node
            soup = BeautifulSoup(str(html_tag), "html.parser")
        else:
            # In case there's no <html>, fallback to entire doc
            soup = soup_all

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


def parse_only_html_body(html_content):
    """
    1. Remove <?xml ...?> if present (so BeautifulSoup doesn't see it as a ProcessingInstruction).
    2. Parse the entire HTML to find <html>.
    3. Create a new BeautifulSoup *just* from the <html> portion.
       => This ensures the top-level root is <html>, so /1/4 can address <body>, etc.
    """
    # Remove any <?xml ...?> line
    lines = html_content.splitlines()
    if lines and lines[0].strip().startswith("<?xml"):
        lines = lines[1:]
    content_no_xml_decl = "\n".join(lines)

    # First parse the full document
    soup_all = BeautifulSoup(content_no_xml_decl, "html.parser")

    # Find the <html> element
    html_tag = soup_all.find("html")
    if html_tag is None:
        # If there's truly no <html>, fallback to the entire soup
        return soup_all

    # Re‐parse just the <html>...</html> string, so that becomes our root
    return BeautifulSoup(str(html_tag), "html.parser")


def parse_kobo_highlights(
    book_prefix, highlight, book_id, spine_index_map
) -> Optional[db.CalibreHighlight]:
    """Parse a kobo highlight and return a calibre highlight."""
    # kobo_n_tag_start, kobo_n_sentence_start = [
    #     int(i) for i in highlight.start_path.split("\\.")[1:]
    # ]
    # kobo_n_tag_end, kobo_n_sentence_end = [
    #     int(i) for i in highlight.end_path.split("\\.")[1:]
    # ]
    # logger.debug(
    #     f"parsing highlight: {highlight.start_path}, "
    #     f"{highlight.end_path}, {highlight.content_path}"
    # )
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
        file = f.read()

        soup = parse_only_html_body(file)

        # I need to extract everything inside the parenthesis 'OEBPS/chapter01.xhtml#point(/1/4/1/1/2/38/1/1:3)' using regex
        start_cfi = re.search(r"\((.*?)\)", highlight.start_path).group(1)
        end_cfi = re.search(r"\((.*?)\)", highlight.end_path).group(1)

        # now I need everything before the #
        real_content_path = highlight.start_path.split("#")[0]

        calibre_start_cfi = convert_cfi_system1_to_system2(soup, start_cfi)
        calibre_end_cfi = convert_cfi_system1_to_system2(soup, end_cfi)

    #     # First find the node using KOBO notation
    #     target_start_node = None
    #     target_end_node = None
    #     kobo_target_start_offset = highlight.start_offset
    #     kobo_target_end_offset = highlight.end_offset
    #     intermidiate_offset = 0
    #     do_append = False
    #     n_tag = 1

    #     first_parent = soup.body

    #     for child in first_parent.descendants:
    #         parent_names = [p.name for p in child.parents]
    #         if "figure" in parent_names:
    #             continue

    #         if (
    #             not isinstance(child, bs4.element.NavigableString)
    #             or isinstance(child, bs4.element.Comment)
    #             or str(child) == "\n"
    #             or str(child) == " "
    #             or str(child) == "\u00A0"  # non-breaking space, used in the tables
    #             or str(child).strip() == ""
    #         ):
    #             continue

    #         logger.debug(f"Including tag #{n_tag}: {child}")

    #         if n_tag == kobo_n_tag_start:
    #             target_start_node = (str(child), child)
    #             child_length = len(str(child))

    #             # Add lengths of previous sentences
    #             kobo_target_start_offset += get_prev_sentences_offset(
    #                 child, kobo_n_sentence_start
    #             )

    #             if kobo_n_tag_start == kobo_n_tag_end:
    #                 target_end_node = target_start_node
    #                 if kobo_n_sentence_start == kobo_n_sentence_end:
    #                     kobo_target_end_offset += (
    #                         kobo_target_start_offset - highlight.start_offset
    #                     )
    #                 else:
    #                     kobo_target_end_offset += get_prev_sentences_offset(
    #                         child, kobo_n_sentence_end
    #                     )
    #                 break
    #             else:
    #                 do_append = True
    #                 intermidiate_offset += child_length

    #         elif n_tag == kobo_n_tag_end:
    #             target_end_node = (str(child), child)
    #             kobo_target_end_offset += get_prev_sentences_offset(
    #                 child, kobo_n_sentence_end
    #             )
    #             break

    #         elif do_append:
    #             intermidiate_offset += len(str(child))

    #         n_tag += 1

    #     if not target_start_node:
    #         logger.debug("Failed to find the target start node")
    #         return None
    #     if not target_end_node:
    #         logger.debug("Failed to find the target end node")
    #         return None

    # start_cfi = encode_cfi(target_start_node[1], kobo_target_start_offset)
    # end_cfi = encode_cfi(target_end_node[1], kobo_target_end_offset)

    unique_uuid = str(
        uuid.uuid3(uuid.NAMESPACE_DNS, f"{start_cfi}*{end_cfi}*{highlight.text})").hex
    )

    calibre_highlight_json = {
        "start_cfi": calibre_start_cfi,
        "end_cfi": calibre_end_cfi,
        "highlighted_text": highlight.text,
        "spine_index": spine_index_map[real_content_path],
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
