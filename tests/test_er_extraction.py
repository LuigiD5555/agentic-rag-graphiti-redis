from src.ner.ner_extraction import NERExtractor


class DummyLLM:
    def __init__(self):
        self.prompt = None

    def complete(self, prompt):
        self.prompt = prompt
        return '{"entities": [{"name": "John", "type": "Person"}], "relations": []}'


class DummyGraph:

    def __init__(self):
        self.entities = []

    def add_entity(self, name, entity_type):
        self.entities.append((name, entity_type))

    def add_relation(self, src, rel, dst):
        pass


def test_ner_extractor_adds_entities():
    """
    Test that the NER extractor adds entities to the graph.
    """
    er = NERExtractor(DummyLLM(), DummyGraph())
    er.extract_and_insert("John works at ACME.")
    assert ("John", "Person") in er.graph.entities
