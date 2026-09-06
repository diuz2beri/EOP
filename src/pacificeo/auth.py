from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException
from jwt import InvalidTokenError

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
    try:
        claims = jwt.decode(
            authorization[7:],
            get_settings().supabase_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="authenticated",
        )
    except InvalidTokenError as exc:
        raise HTTPException(401, "Invalid access token") from exc
    if not claims.get("sub"):
        raise HTTPException(401, "Token subject missing")
    return Principal(user_id=claims["sub"], tenant_id=x_tenant_id)
