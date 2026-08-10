from lingua_relay.asr.metrics import edit_distance, error_rate, normalize_text


def test_edit_distance_counts_substitution_insertion_and_deletion() -> None:
    assert edit_distance(("a", "b", "c"), ("a", "x", "c", "d")) == 2


def test_chinese_and_japanese_use_character_error_rate() -> None:
    errors, units, rate, metric = error_rate("实时翻译。", "实时翻易", "zh")

    assert (errors, units, rate, metric) == (1, 4, 0.25, "cer")


def test_english_and_korean_use_word_error_rate() -> None:
    assert error_rate("Hello, world!", "hello world", "en") == (0, 2, 0, "wer")
    assert error_rate("실시간 번역", "실시간 자막", "ko") == (1, 2, 0.5, "wer")


def test_normalization_removes_punctuation_and_collapses_space() -> None:
    assert normalize_text("ＡＢＣ...  Test") == "abc test"
