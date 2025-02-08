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
    substring_prog1 = text_prog1[:offset_prog1]

    # 2) Decode this substring from the backslash-unicode-escape representation.
    #    - encode('ascii') turns the Python str into raw bytes (ASCII).
    #    - decode('unicode_escape') interprets backslash-escapes like \u041e as Unicode chars.
    decoded_substring = substring_prog1.encode("ascii").decode("unicode_escape")

    # 3) The length of the decoded_substring is how many actual Unicode (program 2) characters
    #    exist before offset_prog1 in the original \uXXXX text.
    offset_prog2 = len(decoded_substring)

    return offset_prog2


# ---------------------------
# Example usage / demonstration
# ---------------------------
if __name__ == "__main__":
    # "Program 1" text (\u-escaped)
    text_prog1 = r"\u041e\u043d \u043f\u043e\u044f\u0432\u0438\u043b\u0441\u044f \u043d\u0430 \u0441\u0432\u0435\u0442..."

    # Let's decode it fully to see what the "program 2" text is:
    text_prog2 = text_prog1.encode("ascii").decode("unicode_escape")
    print("Program 1 text:", text_prog1)
    print("Decoded (Program 2) text:", text_prog2)
    print()

    # Suppose we pick an offset in the Program 1 text that starts exactly at the
    # escape sequence for the 2nd character (the "\u043d" in "\u041e\u043d").
    # The first 6 chars represent '\u041e', the next 6 represent '\u043d'.
    # So if we want the offset at the start of '\u043d', that is offset_prog1 = 6.
    offset_prog1_example = 6

    offset_prog2_example = convert_offset_prog1_to_prog2(
        text_prog1, offset_prog1_example
    )

    print(f"Chosen offset in Program 1 text = {offset_prog1_example}")
    print(f"Corresponding offset in Program 2 text = {offset_prog2_example}")
    print(
        "Program 2 substring from that offset onward:",
        text_prog2[offset_prog2_example:],
    )
