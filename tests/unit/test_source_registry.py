import pytest
from pydantic import ValidationError

from schemas.api.envelope import State
from services.source_registry.registry import Source, load_sources


def test_registry_loads_and_covers_all_states():
    sources = load_sources()
    assert {s.state for s in sources} == set(State)


def test_nothing_is_crawlable_before_source_discovery():
    assert not any(s.crawlable for s in load_sources())


def _source(**overrides) -> dict:
    base = dict(
        id="x", state="MH", name="x", base_url=None, document_types=["GR"],
        languages=["mr"], crawl_method="http", verified=False, terms_reviewed=False,
    )
    return base | overrides


def test_verified_source_must_have_url():
    with pytest.raises(ValidationError):
        Source.model_validate(_source(verified=True))


def test_crawlable_requires_verification_and_terms_review():
    s = Source.model_validate(_source(base_url="https://example.gov.in", verified=True))
    assert not s.crawlable
    s = Source.model_validate(_source(base_url="https://example.gov.in", verified=True, terms_reviewed=True))
    assert s.crawlable
