"""
Who may change official data (Feature K: Amazon Cognito roles).

Three modes, chosen by environment:
  * Cognito   (COGNITO_USER_POOL_ID + COGNITO_CLIENT_ID): a signed access token is required and
              the user's group must match the role: ward_officer or city_planner.
  * Token     (OFFICER_TOKEN only): the older shared secret in the X-Officer-Token header.
  * Open      (neither set): local development, no AWS account needed.
Citizens are never asked to sign in; only officer and planner actions use this.
"""

from __future__ import annotations

import hmac
import os
from functools import lru_cache

from fastapi import Header, HTTPException

WARD_OFFICER, CITY_PLANNER = "ward_officer", "city_planner"
ROLES = (WARD_OFFICER, CITY_PLANNER)


def pool_id() -> str:
    return os.environ.get("COGNITO_USER_POOL_ID", "")


def client_id() -> str:
    return os.environ.get("COGNITO_CLIENT_ID", "")


def mode() -> str:
    if pool_id() and client_id():
        return "cognito"
    return "token" if os.environ.get("OFFICER_TOKEN") else "open"


def _region() -> str:
    return pool_id().split("_", 1)[0]  # pool ids look like us-east-1_AbCdEfGhI


def issuer() -> str:
    return f"https://cognito-idp.{_region()}.amazonaws.com/{pool_id()}"


@lru_cache(maxsize=2)
def _jwks(url: str):
    import jwt
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def _signing_key(token: str):
    return _jwks(issuer() + "/.well-known/jwks.json").get_signing_key_from_jwt(token).key


def verify_access_token(token: str) -> dict:
    """Validated claims of a Cognito access token, or ValueError."""
    import jwt
    try:
        claims = jwt.decode(token, _signing_key(token), algorithms=["RS256"], issuer=issuer(),
                            options={"require": ["exp", "iss", "sub"]})
    except Exception as e:  # bad signature, expired, wrong issuer, unknown key, network …
        raise ValueError(f"invalid token ({type(e).__name__})") from None
    # access tokens carry client_id (not aud); an ID token must not be accepted here
    if claims.get("token_use") != "access" or claims.get("client_id") != client_id():
        raise ValueError("not an access token for this app")
    return claims


def user_from_token(token: str) -> dict:
    claims = verify_access_token(token)
    return {"sub": claims["sub"], "name": claims.get("username", "officer"),
            "groups": [g for g in claims.get("cognito:groups", []) if g in ROLES]}


def require_role(*roles: str):
    """FastAPI dependency: the caller must hold one of `roles`. Returns the user."""
    allowed = set(roles) or set(ROLES)

    def dependency(authorization: str | None = Header(None),
                   x_officer_token: str | None = Header(None)) -> dict:
        m = mode()
        if m == "open":
            return {"sub": "local", "name": "local officer", "groups": list(ROLES)}
        if m == "token":
            if not hmac.compare_digest(x_officer_token or "", os.environ["OFFICER_TOKEN"]):
                raise HTTPException(401, "officer token required")
            return {"sub": "shared-token", "name": "officer", "groups": list(ROLES)}
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "sign in required")
        try:
            user = user_from_token(token)
        except ValueError:
            raise HTTPException(401, "sign in again: the session is not valid") from None
        if not allowed & set(user["groups"]):
            raise HTTPException(403, f"this action needs the role: {' or '.join(sorted(allowed))}")
        return user

    return dependency
