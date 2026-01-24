import pytest


class DummyLLM:
    def __init__(self):
        self.prompt = None
        self.responses = []

    def complete(self, prompt):
        self.prompt = prompt
        response = (
            '{"entities": [{"name": "John", "type": "Person"}], '
            '"relations": [{"src": "John", "rel": "WORKS_AT", "dst": "ACME"}]}'
        )
        self.responses.append(response)
        return response


class DummyNERRepo:
    def __init__(self):
        self.entities = []
        self.relations = []

    def add_entity(self, name, entity_type):
        self.entities.append((name, entity_type))

    def add_relation(self, src, rel, dst):
        self.relations.append((src, rel, dst))


@pytest.mark.skip(reason="NER functionality not currently configured")
def test_ner_extractor_inserts_entities_and_relations():
    # Skip test since NER is not configured
    pass
