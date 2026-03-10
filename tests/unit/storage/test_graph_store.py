import pytest
from src.backends.storage.graph.neo4j_repository import validate_label, validate_relation
from pytest_readable import readable



@readable(
    intent="Verify validate label.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the validate label behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_validate_label():
    assert validate_label("Entity") == "Entity"
    with pytest.raises(ValueError):
        validate_label("123Invalid")


@readable(
    intent="Verify validate relation.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the validate relation behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_validate_relation():
    assert validate_relation("WORKS_AT") == "WORKS_AT"
    with pytest.raises(ValueError):
        validate_relation("invalid-rel")
