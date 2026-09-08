from datetime import UTC, datetime, timedelta

import jwt
import pytest

from pacificeo.tiles import TILE_AUDIENCE, allowed_asset_href, issue_tile_token, verify_tile_token


def test_asset_hosts_are_fail_closed_and_exact_by_default():
    href = "https://products.example.org/tenant-a/product.tif"
    assert allowed_asset_href(href, "products.example.org") == href
    with pytest.raises(ValueError):
        allowed_asset_href(href, "")
    with pytest.raises(ValueError):
        allowed_asset_href("https://products.example.org.evil.test/product.tif", "products.example.org")
    with pytest.raises(ValueError):
        allowed_asset_href("http://products.example.org/product.tif", "products.example.org")


def test_explicit_subdomain_wildcards_do_not_match_the_parent_host():
    assert allowed_asset_href("https://a.storage.test/x.tif", "*.storage.test")
    with pytest.raises(ValueError):
        allowed_asset_href("https://storage.test/x.tif", "*.storage.test")


def test_tile_token_is_bound_to_product_and_tenant():
    secret = "local-unit-test-secret-with-sufficient-length"
    token = issue_tile_token("product-a", "tenant-a", secret, 5)
    assert verify_tile_token(token, "product-a", secret) == "tenant-a"
    with pytest.raises(ValueError):
        verify_tile_token(token, "product-b", secret)


def test_expired_tile_token_is_rejected():
    secret = "local-unit-test-secret-with-sufficient-length"
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "product-a",
            "tenant_id": "tenant-a",
            "aud": TILE_AUDIENCE,
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    with pytest.raises(ValueError):
        verify_tile_token(token, "product-a", secret)
