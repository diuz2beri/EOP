import pytest

from pacificeo.pipeline import normalize_validation
from pacificeo.recipe_config import load_catalog


def test_missing_or_sparse_reference_never_invents_accuracy():
    assert normalize_validation(None, "f1", 250) is None
    assert normalize_validation({"metric":"f1","value":0.99,"reference_pixels":249}, "f1", 250) is None


def test_invalid_accuracy_is_rejected():
    with pytest.raises(ValueError):
        normalize_validation({"metric":"f1","value":1.1,"reference_pixels":500}, "f1", 250)


def test_pacific_recipe_catalog_is_complete():
    catalog = load_catalog()
    assert {"coastal-change","mangrove-extent","flood-extent","vegetation-stress"} <= catalog.recipes.keys()
