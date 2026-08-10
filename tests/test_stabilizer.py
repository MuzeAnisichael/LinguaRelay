from lingua_relay.stabilizer import StablePrefix


def test_emits_only_words_stable_across_two_hypotheses() -> None:
    stabilizer = StablePrefix()

    assert stabilizer.update("the quick") == ""
    assert stabilizer.update("the quick brown") == "the quick"
    assert stabilizer.update("the quick brown fox") == "brown"
    assert stabilizer.finalize("the quick brown fox") == "fox"


def test_reset_starts_a_new_segment() -> None:
    stabilizer = StablePrefix()
    stabilizer.update("first segment")
    stabilizer.finalize("first segment done")

    assert stabilizer.update("new segment") == ""
    assert stabilizer.update("new segment here") == "new segment"


def test_stabilizes_chinese_without_spaces() -> None:
    stabilizer = StablePrefix(language="zh")

    assert stabilizer.update("实时翻") == ""
    assert stabilizer.update("实时翻译") == "实时翻"
    assert stabilizer.finalize("实时翻译") == "译"
