import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "api"),
)

from security import auth  # noqa: E402


@pytest.fixture
def rsa_keys():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    return private_key, private_key.public_key()


@pytest.fixture
def mock_jwks(monkeypatch, rsa_keys):
    _, public_key = rsa_keys

    mock_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(
            key=public_key
        )
    )

    monkeypatch.setattr(
        auth,
        "get_jwks_client",
        lambda: mock_client,
    )


@pytest.fixture
def valid_claims():
    now = datetime.now(timezone.utc)

    return {
        "iss": auth.ISSUER,
        "aud": auth.API_CLIENT_ID,
        "exp": now + timedelta(minutes=30),
        "nbf": now - timedelta(seconds=10),
        "iat": now,
        "ver": "2.0",
        "tid": auth.TENANT_ID,
        "azp": auth.WEB_CLIENT_ID,
        "oid": str(uuid4()),
        "scp": "access_as_user",
    }


def make_token(claims, private_key):
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def authenticate(token):
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token,
    )

    return asyncio.run(
        auth.get_current_user(credentials)
    )


def test_missing_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.get_current_user(None))

    assert exc.value.status_code == 401


def test_valid_token(valid_claims, rsa_keys, mock_jwks):
    private_key, _ = rsa_keys
    token = make_token(valid_claims, private_key)

    user = authenticate(token)

    assert user["user_id"] == valid_claims["oid"]
    assert user["tenant_id"] == auth.TENANT_ID


def test_invalid_signature(valid_claims, rsa_keys, mock_jwks):
    wrong_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    token = make_token(valid_claims, wrong_private_key)

    with pytest.raises(HTTPException) as exc:
        authenticate(token)

    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://example.com"),
        ("aud", "wrong-api"),
        ("tid", str(uuid4())),
        ("azp", "wrong-client"),
        ("ver", "1.0"),
        ("oid", "invalid-user-id"),
    ],
)
def test_invalid_claims(
    claim,
    value,
    valid_claims,
    rsa_keys,
    mock_jwks,
):
    private_key, _ = rsa_keys
    claims = {**valid_claims, claim: value}
    token = make_token(claims, private_key)

    with pytest.raises(HTTPException) as exc:
        authenticate(token)

    assert exc.value.status_code == 401


def test_expired_token(valid_claims, rsa_keys, mock_jwks):
    private_key, _ = rsa_keys

    claims = {
        **valid_claims,
        "exp": datetime.now(timezone.utc)
        - timedelta(minutes=5),
    }

    token = make_token(claims, private_key)

    with pytest.raises(HTTPException) as exc:
        authenticate(token)

    assert exc.value.status_code == 401


def test_missing_scope(valid_claims, rsa_keys, mock_jwks):
    private_key, _ = rsa_keys

    claims = {
        **valid_claims,
        "scp": "other_scope",
    }

    token = make_token(claims, private_key)

    with pytest.raises(HTTPException) as exc:
        authenticate(token)

    assert exc.value.status_code == 403


def test_app_only_token(valid_claims, rsa_keys, mock_jwks):
    private_key, _ = rsa_keys

    claims = {
        **valid_claims,
        "idtyp": "app",
    }

    token = make_token(claims, private_key)

    with pytest.raises(HTTPException) as exc:
        authenticate(token)

    assert exc.value.status_code == 401
