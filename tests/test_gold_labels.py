import pytest

from nlp.gold_labels import parse_gold_label_cell


def test_parse_pos_neg_neu():
    assert parse_gold_label_cell("pos") == 2
    assert parse_gold_label_cell("neg") == 0
    assert parse_gold_label_cell("neu") == 1
    assert parse_gold_label_cell(2) == 2


def test_parse_rejects_bool():
    with pytest.raises(ValueError):
        parse_gold_label_cell(True)
