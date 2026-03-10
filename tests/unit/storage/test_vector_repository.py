from src.backends.storage.vector.weaviate_repository import WeaviateRepository
from pytest_readable import readable



class _ExcStub:
    def __init__(self, status_code=None, message=""):
        self.status_code = status_code
        self.message = message


@readable(
    intent="Verify is not found error detects 404 and message variants.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the is not found error detects 404 and message variants behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_is_not_found_error_detects_404_and_message_variants():
    assert WeaviateRepository._is_not_found_error(_ExcStub(status_code=404))
    assert WeaviateRepository._is_not_found_error(_ExcStub(status_code=500, message="No object with id 'x'"))
    assert not WeaviateRepository._is_not_found_error(_ExcStub(status_code=500, message="validation failed"))


@readable(
    intent="Verify detect vector dimension mismatch parses dims.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the detect vector dimension mismatch parses dims behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
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
