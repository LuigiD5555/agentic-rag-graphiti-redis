"""Unit tests for OfficeToolClient runtime behavior."""

from src.workflows.ingestion.loaders.office_client import OfficeToolClient
from pytest_readable import readable



class _ResponseStub:
    def __init__(self, status_code: int):
        self.status_code = status_code


@readable(
    intent="Validate the currently supported resiliency surface:.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the resilience pattern behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_resilience_pattern(monkeypatch):
    """
    Validate the currently supported resiliency surface:
    - configured base_url/timeout
    - health endpoint behavior
    """
    client = OfficeToolClient()
    assert isinstance(client.base_url, str) and client.base_url
    assert isinstance(client.timeout, int) and client.timeout > 0

    monkeypatch.setattr(
        "src.workflows.ingestion.loaders.office_client.requests.get",
        lambda *args, **kwargs: _ResponseStub(200),
    )
    assert client.health_check() is True
