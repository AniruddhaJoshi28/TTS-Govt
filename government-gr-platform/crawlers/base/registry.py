"""Adapter registry: maps the ``adapter:`` key in sources.yaml to an implementation."""

from __future__ import annotations

from core.config.sources import SourceConfig
from crawlers.base.adapter import SourceAdapter
from crawlers.base.http import PoliteClient


def _registry() -> dict[str, type[SourceAdapter]]:
    from crawlers.madhya_pradesh.socialjustice import MPSocialJusticeAdapter
    from crawlers.maharashtra.gr_portal import MaharashtraGRPortalAdapter
    from crawlers.maharashtra.orgpedia_seed import MaharashtraOrgpediaSeedAdapter
    from crawlers.odisha.drupal_views import OdishaDrupalViewsAdapter
    from crawlers.odisha.egazette import OdishaEGazetteAdapter

    adapters = [
        MaharashtraGRPortalAdapter,
        MaharashtraOrgpediaSeedAdapter,
        OdishaDrupalViewsAdapter,
        OdishaEGazetteAdapter,
        MPSocialJusticeAdapter,
    ]
    return {a.name: a for a in adapters}


def build_adapter(source: SourceConfig, client: PoliteClient | None = None) -> SourceAdapter:
    if not source.adapter:
        raise ValueError(f"source {source.key} has no adapter (status {source.status})")
    try:
        cls = _registry()[source.adapter]
    except KeyError as exc:
        raise ValueError(f"unknown adapter {source.adapter!r}") from exc
    return cls(source, client)
