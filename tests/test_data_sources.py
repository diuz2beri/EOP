from pathlib import Path

import yaml


def test_connected_stac_sources_match_aoi_choices():
    registry = yaml.safe_load(Path("config/data_sources.yaml").read_text(encoding="utf-8"))
    earth_search = registry["sources"]["earth-search"]

    assert earth_search["status"] == "connected"
    assert set(earth_search["collections"]) == {"sentinel-2-l2a", "landsat-c2-l2"}


def test_registry_prohibits_invented_scientific_values():
    registry = yaml.safe_load(Path("config/data_sources.yaml").read_text(encoding="utf-8"))

    assert registry["policy"]["accuracy_missing_state"] == "unavailable"
    assert registry["policy"]["prohibit_unapproved_composite_indices"] is True
