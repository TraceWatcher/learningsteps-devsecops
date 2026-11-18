from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWTError

TENANT_ID = "c0531484-50fa-4ff2-97df-b1f2d4810603"
API_CLIENT_ID = "dc797bb1-a255-4714-8910-a09e876100e9"
WEB_CLIENT_ID = "0ff6b105-66c2-4848-99ac-0f57a375d499"

ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
JWKS_URL = (
    f"https://login.microsoftonline.com/{TENANT_ID}"
    "/discovery/v2.0/keys"
)

REQUIRED_SCOPE = "access_as_user"

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def get_jwks_client():
    return PyJWKClient(
        JWKS_URL,
        cache_jwk_set=True,
        lifespan=3600,
        timeout=5,
    )


def verify_access_token(token: str) -> dict:
    """Validate an Entra ID access token for LearningSteps."""

    signing_key = get_jwks_client().get_signing_key_from_jwt(token)

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=API_CLIENT_ID,
        issuer=ISSUER,
        options={
            "require": ["exp", "iss", "aud"],
        },
        leeway=30,
    )

    if claims.get("ver") != "2.0":
        raise jwt.InvalidTokenError("Unexpected token version")

    if claims.get("tid") != TENANT_ID:
        raise jwt.InvalidTokenError("Unexpected tenant")

    if claims.get("azp") != WEB_CLIENT_ID:
        raise jwt.InvalidTokenError("Unauthorized client application")

    owner_id = claims.get("oid")

    try:
        UUID(owner_id)
    except (TypeError, ValueError, AttributeError):
        raise jwt.InvalidTokenError(
            "Invalid user object ID"
        ) from None

    if claims.get("idtyp") == "app":
        raise jwt.InvalidTokenError("Application tokens not allowed")

    return claims


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
) -> dict:
    """Require a valid delegated Entra ID access token."""

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = await run_in_threadpool(
            verify_access_token,
            credentials.credentials,
        )
    except (PyJWTError, ValueError, TimeoutError, OSError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    scopes = claims.get("scp", "").split()

    if REQUIRED_SCOPE not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    return {
        "user_id": claims["oid"],
        "tenant_id": claims["tid"],
    }
