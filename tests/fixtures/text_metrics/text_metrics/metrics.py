from .helpers import character_count as count_characters

SEPARATORS = " \t\n\r\v\f"


def metrics(text):
    if not isinstance(text, str):
        raise TypeError("text must be str")
    characters = count_characters(text)
    words = 0
    lines = 0
    inside_word = False
    if text:
        lines = 1
    for character in text:
        if character == "\n":
            lines = lines + 1
        if character in SEPARATORS:
            inside_word = False
        elif not inside_word:
            words = words + 1
            inside_word = True
    return characters, words, lines
