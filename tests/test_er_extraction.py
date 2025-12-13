from src.ner.extractor import NERExtractor


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


def test_ner_extractor_inserts_entities_and_relations():
    extractor = NERExtractor(DummyLLM(), DummyNERRepo())
    extractor.extract_and_insert("John works at ACME.")

    assert ("John", "Person") in extractor.repo.entities
    assert ("John", "WORKS_AT", "ACME") in extractor.repo.relations
