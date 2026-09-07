from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError

from pacificeo.settings import get_settings


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str


def principal_from_headers(
    authorization: str = Header(...), x_tenant_id: str = Header(...),
) -> Principal:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    token = authorization[7:]
    settings = get_settings()
    try:
        algorithm = jwt.get_unverified_header(token).get("alg")
        if algorithm == "HS256":
            if settings.supabase_jwt_secret is None:
                raise HTTPException(503, "Legacy JWT verification is not configured")
            key = settings.supabase_jwt_secret.get_secret_value()
            algorithms = ["HS256"]
        elif algorithm in {"ES256", "RS256"}:
            if not settings.supabase_url:
                raise HTTPException(503, "Supabase URL is not configured")
            jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
            key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
            algorithms = [algorithm]
        else:
            raise HTTPException(401, "Unsupported access token algorithm")
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience="authenticated",
        )
    except (InvalidTokenError, PyJWKClientError) as exc:
        raise HTTPException(401, "Invalid access token") from exc
    if not claims.get("sub"):
        raise HTTPException(401, "Token subject missing")
    return Principal(user_id=claims["sub"], tenant_id=x_tenant_id)
