from agent.numbers_check import collect_allowed, find_unsupported, numbers_in


def test_extracts_plain_decimal_comma_and_devanagari():
    assert numbers_in("Score 12.50 and 1,234 people; ५ sites") == {"12.5", "1234", "5"}


def test_list_markers_are_not_numbers():
    assert numbers_in("1. Plant trees\n2) Add shade") == set()


def test_unsupported_number_is_flagged():
    allowed = collect_allowed({"rank": 3, "cost": 120.5})
    assert find_unsupported("Ward ranks 3, cost 120.5 lakh", allowed) == []
    assert find_unsupported("Ward ranks 3, cost 999 lakh", allowed) == ["999"]


def test_negative_cooling_matches_magnitude():
    allowed = collect_allowed({"cooling_low_c": -0.84, "cooling_high_c": -2.1})
    assert find_unsupported("estimated cooling 0.84 to 2.1 °C", allowed) == []


def test_guidance_numbers_are_allowed_when_included():
    allowed = collect_allowed({}, "call 112 or 108")
    assert find_unsupported("call 112 or 108", allowed) == []
