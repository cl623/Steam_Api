from nlp.preprocess import clean_text, tokenize_simple
from nlp.weak_labels import weak_sentiment_label


def test_clean_text_strips_url_and_lowercase():
    s = clean_text("Check https://evil.test/x @user STEAM_0:1:234 insane!!!")
    assert "https" not in s
    assert "insane" in s


def test_tokenize_simple():
    assert "nice" in tokenize_simple("NT wp!!!")


def test_weak_sentiment_basic():
    assert weak_sentiment_label("insane clutch love this") == "pos"
    assert weak_sentiment_label("terrible throw disband") == "neg"
    assert weak_sentiment_label("maybe later") == "neu"
