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


def test_exposes_stable_and_unstable_regions_for_rendering() -> None:
    stabilizer = StablePrefix(language="ko")

    first = stabilizer.update_state("실시간 번역")
    second = stabilizer.update_state("실시간 번역 자막")
    final = stabilizer.finalize_state("실시간 번역 자막입니다")

    assert first.stable_text == ""
    assert first.unstable_text == "실시간 번역"
    assert second.stable_text == "실시간 번역"
    assert second.unstable_text == "자막"
    assert final.stable_text == "실시간 번역 자막입니다"
    assert final.unstable_text == ""


def test_committed_prefix_does_not_retract_when_one_hypothesis_diverges() -> None:
    stabilizer = StablePrefix(language="en")
    stabilizer.update_state("the quick")
    committed = stabilizer.update_state("the quick brown")
    divergent = stabilizer.update_state("a quick brown")

    assert committed.stable_text == "the quick"
    assert divergent.text == "the quick"
    assert divergent.stable_text == "the quick"
    assert divergent.unstable_text == ""
