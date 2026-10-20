from importlib.resources import files


def stopword_text():
    return files("text_metrics").joinpath("stopwords.txt").read_text(encoding="utf-8")
