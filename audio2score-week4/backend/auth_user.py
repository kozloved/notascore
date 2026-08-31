"""Validate Supabase access tokens. Never trust a user_id from the client body."""

from __future__ import annotations

import os

import jwt

NOT_FOUND_DETAIL = "Score not found"
SIGN_IN_DETAIL = "Please sign in to continue."


def auth_configured() -> bool:
    return bool(
        os.getenv("SUPABASE_JWT_SECRET")
        or (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        or os.getenv("SUPABASE_URL")
    )


def user_id_from_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return user_id_from_token(token.strip())


def user_id_from_token(token: str) -> str | None:
    try:
        payload = _decode_token(token)
    except Exception:
        return None
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        return None
    return sub


def _decode_token(token: str) -> dict:
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if secret:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    if not url:
        raise RuntimeError("JWT is not configured")

    jwks_url = f"{url}/auth/v1/.well-known/jwks.json"
    client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    signing_key = client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256", "HS256"],
        audience="authenticated",
    )
