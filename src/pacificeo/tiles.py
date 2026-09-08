from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import jwt
from jwt import InvalidTokenError

TILE_AUDIENCE = "pacificeo-tiles"


def allowed_asset_href(href: str, configured_hosts: str) -> str:
    """Validate a product asset against an explicit HTTPS host allowlist."""
    parsed = urlparse(href)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Product asset must be an HTTPS URL without embedded credentials")
    if parsed.fragment:
        raise ValueError("Product asset URL fragments are not allowed")
    host = parsed.hostname.lower().rstrip(".")
    rules = [rule.strip().lower().rstrip(".") for rule in configured_hosts.split(",") if rule.strip()]
    if not rules:
        raise ValueError("No product asset hosts are configured")
    permitted = any(
        host == rule or (rule.startswith("*.") and host.endswith(rule[1:]) and host != rule[2:])
        for rule in rules
    )
    if not permitted:
        raise ValueError("Product asset host is not permitted")
    return href


def issue_tile_token(
    product_id: str,
    tenant_id: str,
    secret: str,
    lifetime_minutes: int,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": product_id,
            "tenant_id": tenant_id,
            "aud": TILE_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=lifetime_minutes),
        },
        secret,
        algorithm="HS256",
    )


def verify_tile_token(token: str, product_id: str, secret: str) -> str:
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience=TILE_AUDIENCE)
    except InvalidTokenError as exc:
        raise ValueError("Invalid or expired tile token") from exc
    if claims.get("sub") != product_id or not claims.get("tenant_id"):
        raise ValueError("Tile token does not match this product")
    return str(claims["tenant_id"])
