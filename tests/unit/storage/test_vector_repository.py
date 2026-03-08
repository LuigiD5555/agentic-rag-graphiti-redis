from src.backends.storage.vector.weaviate_repository import WeaviateRepository


class _ExcStub:
    def __init__(self, status_code=None, message=""):
        self.status_code = status_code
        self.message = message


def test_is_not_found_error_detects_404_and_message_variants():
    assert WeaviateRepository._is_not_found_error(_ExcStub(status_code=404))
    assert WeaviateRepository._is_not_found_error(_ExcStub(status_code=500, message="No object with id 'x'"))
    assert not WeaviateRepository._is_not_found_error(_ExcStub(status_code=500, message="validation failed"))


def test_detect_vector_dimension_mismatch_parses_dims():
    exc = _ExcStub(
        status_code=422,
        message=(
            "vector dimensions do not match: new node has a vector with length 768. "
            "Existing nodes have vectors with length 384"
        ),
    )

    dims = WeaviateRepository._detect_vector_dimension_mismatch(exc)
    assert dims == (768, 384)
