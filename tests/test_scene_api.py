import os
from types import SimpleNamespace
from uuid import UUID

os.environ.setdefault("PACIFICEO_DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")

from pacificeo.api import list_aoi_scenes


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
