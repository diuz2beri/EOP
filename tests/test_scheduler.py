from datetime import UTC, datetime

from pacificeo.scheduler import DueAoi, StacClient, extract_cog_href


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"features": [{"id": "scene-1"}]}


class FakeHttpClient:
    def __init__(self):
        self.request = None

    def post(self, url, json):
        self.request = (url, json)
        return FakeResponse()


def test_stac_search_is_driven_by_aoi_config():
    http = FakeHttpClient()
    client = StacClient("https://stac.test/v1/", http)  # type: ignore[arg-type]
    aoi = DueAoi(
        id="a", tenant_id="t", name="reef", geometry={"type": "Polygon", "coordinates": []},
        cadence_days=5, cloud_threshold=12.5, product_recipes=["reef-health"],
        stac_collections=["sentinel-2-l2a"], last_scheduled_at=None,
    )
    result = client.search(aoi, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
    assert result == [{"id": "scene-1"}]
    assert http.request[1]["collections"] == ["sentinel-2-l2a"]
    assert http.request[1]["query"] == {"eo:cloud_cover": {"lte": 12.5}}


def test_extract_cog_prefers_named_assets():
    assert extract_cog_href({"assets": {"visual": {"href": "s3://bucket/scene.tif"}}}) == "s3://bucket/scene.tif"


def test_extract_cog_falls_back_to_geotiff():
    item = {"assets": {"classification": {"href": "https://x/c.tif", "type": "image/geotiff"}}}
    assert extract_cog_href(item) == "https://x/c.tif"
