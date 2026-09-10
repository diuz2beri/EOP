import os
from types import SimpleNamespace
from uuid import UUID

os.environ.setdefault("PACIFICEO_DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")

from fastapi import HTTPException

from pacificeo.api import annual_coverage, discover_aoi_year, list_aoi_scenes


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.info = {"principal": SimpleNamespace(tenant_id="tenant-a")}
        self.rows = rows
        self.params = None

    def execute(self, _statement, params):
        self.params = params
        return FakeResult(self.rows)


def test_list_aoi_scenes_is_tenant_scoped_and_filters_unsafe_preview_urls():
    session = FakeSession(
        [
            {
                "scene_id": "safe-scene",
                "preview_href": "https://example.test/preview.jpg",
            },
            {
                "scene_id": "unsafe-scene",
                "preview_href": "http://example.test/preview.jpg",
            },
        ]
    )
    aoi_id = UUID("11111111-1111-1111-1111-111111111111")

    scenes = list_aoi_scenes(aoi_id, 12, session)

    assert session.params == {"tenant": "tenant-a", "aoi": aoi_id, "limit": 12}
    assert scenes[0]["preview_href"] == "https://example.test/preview.jpg"
    assert scenes[1]["preview_href"] is None


def test_annual_coverage_is_tenant_scoped_and_does_not_claim_a_mosaic():
    session = FakeSession(
        [
            {
                "year": 2025,
                "coverage_pct": 100.0,
                "preview_href": "https://example.test/preview.jpg",
            },
            {
                "year": 2026,
                "coverage_pct": 78.4,
                "preview_href": "http://example.test/preview.jpg",
            },
        ]
    )
    aoi_id = UUID("11111111-1111-1111-1111-111111111111")

    years = annual_coverage(aoi_id, session)

    assert session.params == {"tenant": "tenant-a", "aoi": aoi_id}
    assert years[0]["coverage_complete"] is True
    assert years[0]["display_kind"] == "clearest_approved_scene"
    assert years[1]["coverage_complete"] is False
    assert years[1]["preview_href"] is None


def test_historical_discovery_rejects_unsupported_years_before_querying_stac():
    session = FakeSession([])
    session.info["role"] = "admin"

    try:
        discover_aoi_year("aoi-a", 1900, session)
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Expected historical year validation to fail")
