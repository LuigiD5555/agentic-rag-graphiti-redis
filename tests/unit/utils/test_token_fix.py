"""Pytest coverage for token calculation utilities."""

from src.utils.text import effective_limit, _estimate_token_count, truncate_to_token_limit
from pytest_readable import readable



@readable(
    intent="Verify effective limit applies margin.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the effective limit applies margin behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_effective_limit_applies_margin():
    assert effective_limit(480) == 432
    assert effective_limit(400) == 360
    assert effective_limit(10) == 7
    assert effective_limit(0) == 0


@readable(
    intent="Verify estimate token count is conservative.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the estimate token count is conservative behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_estimate_token_count_is_conservative():
    assert _estimate_token_count("") == 0
    assert _estimate_token_count("abcdefghi") == 3
    assert _estimate_token_count("a b c d e f g h i") >= 3


@readable(
    intent="Verify truncate to token limit reduces text.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the truncate to token limit reduces text behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_truncate_to_token_limit_reduces_text():
    text = "This is a test sentence with some words. " * 50
    truncated = truncate_to_token_limit(text, 10, "test-model")

    assert truncated
    assert len(truncated) < len(text)
    assert _estimate_token_count(truncated) <= 10


@readable(
    intent="Verify truncate with zero limit returns input.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the truncate with zero limit returns input behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_truncate_with_zero_limit_returns_input():
    text = "Short text."
    assert truncate_to_token_limit(text, 0, "test-model") == text
