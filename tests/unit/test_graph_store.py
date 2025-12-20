import pytest
from src.storage.graph.neo4j_repository import validate_label, validate_relation


def test_validate_label():
    assert validate_label("Entity") == "Entity"
    with pytest.raises(ValueError):
        validate_label("123Invalid")


def test_validate_relation():
    assert validate_relation("WORKS_AT") == "WORKS_AT"
    with pytest.raises(ValueError):
        validate_relation("invalid-rel")
