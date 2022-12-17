import spacy
from spacy.language import Language
import pytest
from sentence_tokenizer import tokenize_epub_sentences


nlp = spacy.load("en_core_web_sm")

text_1 = (
    "In the year 1878 I took my degree of Doctor of Medicine of the University of \n"
    "London, and proceeded to Netley to go through the course prescribed for \n"
    "surgeons in the army. Having completed my studies there, I was duly attached to \n"
    "the Fifth Northumberland Fusiliers as Assistant Surgeon. The regiment was \n"
    "stationed in India at the time, and before I could join it, the second Afghan \n"
    "war had broken out. On landing at Bombay, I learned that my corps had advanced \n"
    "through the passes, and was already deep in the enemy’s country. I followed, \n"
    "however, with many other officers who were in the same situation as myself, and \n"
    " succeeded in reaching Candahar in safety, where I found my regiment, and at \n"
    "once entered upon my new duties."
)
expected_tokenized_text_1 = []


text_2 = (
    "“Whatever have you been doing with yourself, Watson?” he asked in undisguised \n"
    "wonder, as we rattled through the crowded London streets. “You are as thin as a \n"
    "lath and as brown as a nut.”"
)

text_3 = "As stated above, e.g. is short for “for example.”"

text_4 = (
    "After work, I’m going to try the new restaurant (i.e., All About Pasta) \n"
    "to decide on a venue for the reception."
)

text_5 = (
    "“Oh! a mystery is it?” I cried, rubbing my hands. “This is very piquant. I am \n"
    "much obliged to you for bringing us together. ‘The proper study of mankind is \n"
    "man,’ you know.”"
)


def from_spacy(text: str):
    return [t.text_with_ws for t in nlp(str(text)).sents]


@pytest.mark.parametrize(
    "text",
    [text_1, text_2, text_3, text_4, text_5],
)
def test_compare_spacy_and_custom_tokenizer(text):
    # print(from_spacy(text))
    # print(tokenize_epub_sentences(text))
    assert tokenize_epub_sentences(text) == from_spacy(text)
