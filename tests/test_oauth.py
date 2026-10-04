"""Tests for OAuth 2.1 authentication, RFC 9728 Protected Resource Metadata,
RFC 8414 Authorization Server Metadata, and multi-tenant token isolation.
"""

import time
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.context import (
    clear_user_id_cache,
    get_cached_user_id,
    set_current_auth,
)
from app.auth.models import ProtectedResourceMetadata, TokenPayload
from app.auth.verifier import JWKSVerifier, TokenVerificationError, token_verifier
from app.config import settings
from app.database import async_session_factory
from app.main import app
from app.mcp.tools import (
    list_trackers,
    resolve_effective_user_id,
    track_subject,
)
from app.repositories.offer_repository import OfferRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.subject_repository import SubjectRepository
from app.repositories.user_repository import UserRepository

TEST_SECRET = "test-secret-signing-key-for-dealwatch-phase8-testing"


def create_token(
    sub: str,
    email: str | None = None,
    scopes: list[str] | None = None,
    secret: str = TEST_SECRET,
    expires_in: int = 3600,
    issuer: str | None = None,
    audience: str | None = None,
) -> str:
    """Helper to generate HS256 signed test JWT tokens."""
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email or f"{sub}@example.com",
        "scope": " ".join(scopes) if scopes else "dealwatch:read dealwatch:write",
        "iat": now,
        "exp": now + expires_in,
    }
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def setup_auth_settings():
    """Configures test settings and cleans up test state between tests."""
    original_auth_required = settings.AUTH_REQUIRED
    original_test_secret = settings.AUTH_TEST_SECRET
    original_issuer = settings.AUTH_ISSUER
    original_audience = settings.AUTH_AUDIENCE
    original_jwks_url = settings.AUTH_JWKS_URL

    token_verifier.test_secret = TEST_SECRET
    settings.AUTH_TEST_SECRET = TEST_SECRET
    clear_user_id_cache()

    yield

    token_verifier.test_secret = original_test_secret
    settings.AUTH_TEST_SECRET = original_test_secret
    settings.AUTH_REQUIRED = original_auth_required
    settings.AUTH_ISSUER = original_issuer
    settings.AUTH_AUDIENCE = original_audience
    settings.AUTH_JWKS_URL = original_jwks_url
    clear_user_id_cache()


# -----------------------------------------------------------------------------
# 1. RFC 9728 Protected Resource Metadata
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rfc9728_protected_resource_metadata():
    """Tests GET /.well-known/oauth-protected-resource returns RFC 9728 compliant JSON."""
    settings.AUTH_ISSUER = "https://auth.dealwatch.example.com"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.get("/.well-known/oauth-protected-resource")
        assert res.status_code == 200
        data = res.json()

        metadata = ProtectedResourceMetadata(**data)
        assert metadata.resource == "http://127.0.0.1:8000/mcp"
        assert metadata.authorization_servers == ["https://auth.dealwatch.example.com"]
        assert "dealwatch:read" in metadata.scopes_supported
        assert "dealwatch:write" in metadata.scopes_supported
        assert metadata.bearer_methods_supported == ["header"]
        assert metadata.resource_documentation == "https://github.com/samarth-sxngh/dealwatch"


# -----------------------------------------------------------------------------
# 2. RFC 8414 Authorization Server Metadata
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rfc8414_authorization_server_metadata_configured():
    """Tests GET /.well-known/oauth-authorization-server when AUTH_ISSUER is configured."""
    settings.AUTH_ISSUER = "https://auth.example.com"
    settings.AUTH_JWKS_URL = "https://auth.example.com/.well-known/jwks.json"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.get("/.well-known/oauth-authorization-server")
        assert res.status_code == 200
        data = res.json()
        assert data["issuer"] == "https://auth.example.com"
        assert data["jwks_uri"] == "https://auth.example.com/.well-known/jwks.json"
        assert "dealwatch:read" in data["scopes_supported"]


@pytest.mark.asyncio
async def test_rfc8414_authorization_server_metadata_not_configured():
    """Tests GET /.well-known/oauth-authorization-server returns 404 when AUTH_ISSUER is empty."""
    settings.AUTH_ISSUER = None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.get("/.well-known/oauth-authorization-server")
        assert res.status_code == 404
        assert res.json()["error"] == "not_configured"


# -----------------------------------------------------------------------------
# 3. Unauthenticated /mcp access control
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mcp_unauthenticated_allowed_when_auth_not_required():
    """When AUTH_REQUIRED is False (default), OAuth2Middleware allows /mcp requests through to call_next."""
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

    from app.auth.middleware import OAuth2Middleware

    settings.AUTH_REQUIRED = False
    middleware = OAuth2Middleware(app=None)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [],
    }
    request = Request(scope)

    called = False

    async def mock_call_next(req):
        nonlocal called
        called = True
        return PlainTextResponse("ok")

    response = await middleware.dispatch(request, mock_call_next)
    assert called is True
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_mcp_unauthenticated_rejected_when_auth_required():
    """When AUTH_REQUIRED is True, missing bearer token yields 401 with RFC 9728 challenge."""
    settings.AUTH_REQUIRED = True

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401
        data = res.json()
        assert data["error"] == "unauthorized"
        assert data["resource_metadata"] == "/.well-known/oauth-protected-resource"

        www_auth = res.headers.get("WWW-Authenticate", "")
        assert 'Bearer error="invalid_token"' in www_auth
        assert 'resource_metadata="/.well-known/oauth-protected-resource"' in www_auth


# -----------------------------------------------------------------------------
# 4. Invalid, Malformed, and Expired Tokens
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mcp_invalid_token_returns_401():
    """Malformed or invalid JWT bearer token returns 401 with challenge header."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.post(
            "/mcp",
            headers={"Authorization": "Bearer this-is-not-a-valid-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
        assert res.status_code == 401
        assert res.json()["error"] == "invalid_token"
        assert "WWW-Authenticate" in res.headers
        assert 'Bearer error="invalid_token"' in res.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_mcp_expired_token_returns_401():
    """Expired JWT token returns 401 with invalid_token error description."""
    expired_token = create_token(sub="user-expired", expires_in=-300)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {expired_token}"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
        assert res.status_code == 401
        assert res.json()["error"] == "invalid_token"
        assert "expired" in res.json()["message"].lower()


@pytest.mark.asyncio
async def test_verifier_token_validation_edge_cases():
    """Tests verifier unit errors for empty tokens, missing sub, and signature mismatch."""
    verifier = JWKSVerifier(test_secret=TEST_SECRET)

    # Empty token
    with pytest.raises(TokenVerificationError, match="cannot be empty"):
        verifier.verify_token("")

    # Wrong signature secret
    wrong_sig_token = jwt.encode(
        {"sub": "user-1"}, "wrong-secret-signing-key-32-bytes-long!", algorithm="HS256"
    )
    with pytest.raises(TokenVerificationError, match="Invalid token"):
        verifier.verify_token(wrong_sig_token)

    # Missing sub claim
    no_sub_token = jwt.encode(
        {"email": "test@example.com", "exp": int(time.time()) + 3600},
        TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenVerificationError, match="missing mandatory 'sub'"):
        verifier.verify_token(no_sub_token)


# -----------------------------------------------------------------------------
# 5. User Resolution, In-Memory Caching, and /api/v1/auth/me
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_token_resolves_and_caches_database_user():
    """Valid token creates User in DB and caches mapping in memory to eliminate WAN latency."""
    test_sub = f"oauth-user-{uuid.uuid4().hex[:8]}"
    test_email = f"{test_sub}@dealwatch.io"
    valid_token = create_token(sub=test_sub, email=test_email, scopes=["dealwatch:read"])

    assert get_cached_user_id(test_sub) is None

    # First request: resolves from database and populates cache
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["authenticated"] is True
        assert data["sub"] == test_sub
        assert data["email"] == test_email
        assert data["scopes"] == ["dealwatch:read"]
        user_uuid = uuid.UUID(data["user_id"])

        # In-memory cache is populated
        assert get_cached_user_id(test_sub) == user_uuid

        # Second request: served instantly via cached user UUID
        res2 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert res2.status_code == 200
        assert res2.json()["user_id"] == str(user_uuid)


@pytest.mark.asyncio
async def test_auth_me_unauthenticated():
    """GET /api/v1/auth/me returns unauthenticated status when no token is passed."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    ) as client:
        res = await client.get("/api/v1/auth/me")
        assert res.status_code == 200
        assert res.json()["authenticated"] is False
        assert res.json()["user_id"] is None


# -----------------------------------------------------------------------------
# 6. RS256 Remote JWKS Verification Mock
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rs256_jwks_mock_verification():
    """Tests RS256 token verification against simulated remote JWKS client."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    rs256_token = jwt.encode(
        {
            "sub": "rs256-sub",
            "email": "rs256@example.com",
            "scope": "dealwatch:read",
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )

    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key

    mock_jwks_client = MagicMock()
    mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

    settings.AUTH_TEST_SECRET = None
    verifier = JWKSVerifier(jwks_url="https://mock.descope.com/v1/keys", test_secret=None)
    verifier.jwks_client = mock_jwks_client

    payload = verifier.verify_token(rs256_token)
    assert payload.sub == "rs256-sub"
    assert payload.email == "rs256@example.com"
    assert payload.scopes == ["dealwatch:read"]


# -----------------------------------------------------------------------------
# 7. Multi-Tenant Tracker Isolation
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multi_tenant_user_tracker_isolation():
    """Verifies that trackers created by User A are completely hidden from User B."""
    # Setup two distinct users
    user_a_sub = f"user-a-{uuid.uuid4().hex[:6]}"
    user_b_sub = f"user-b-{uuid.uuid4().hex[:6]}"

    async with async_session_factory() as session:
        subject_repo = SubjectRepository(session)
        source_repo = SourceRepository(session)
        offer_repo = OfferRepository(session)
        user_repo = UserRepository(session)

        user_a = await user_repo.get_or_create(oauth_sub=user_a_sub, email="a@dealwatch.local")
        user_b = await user_repo.get_or_create(oauth_sub=user_b_sub, email="b@dealwatch.local")

        subject = await subject_repo.create_product_subject(
            normalized_key=f"tenant-sub-{uuid.uuid4().hex[:6]}",
            title="Isolated Item",
        )
        source = await source_repo.get_or_create(
            domain="store.local", name="Store", country="IN", currency="INR"
        )
        offer = await offer_repo.save_or_update_offer(
            subject_id=subject.id,
            source_id=source.id,
            canonical_url=f"https://store.local/p/{uuid.uuid4().hex[:8]}",
            currency="INR",
            total_price=Decimal("1500.00"),
            match_status="exact",
        )
        await session.commit()
        subj_id = str(subject.id)
        off_id = str(offer.id)
        user_a_id = user_a.id
        user_b_id = user_b.id

    token_a = TokenPayload(sub=user_a_sub, email="a@dealwatch.local", scopes=["dealwatch:write"])
    token_b = TokenPayload(sub=user_b_sub, email="b@dealwatch.local", scopes=["dealwatch:read"])

    # 1. User A creates a tracker under their context
    set_current_auth(token_a, user_a_id)
    track_res = await track_subject(
        subject_id=subj_id,
        offer_ids=[off_id],
        target_price=1200.0,
    )
    assert track_res["status"] == "active"
    tracker_id = track_res["tracker_id"]

    # User A lists trackers -> sees 1 tracker
    list_a = await list_trackers(status="active")
    assert any(t["tracker_id"] == tracker_id for t in list_a["trackers"])

    # 2. Switch context to User B -> lists trackers
    set_current_auth(token_b, user_b_id)
    list_b = await list_trackers(status="active")
    # User B should NOT see User A's tracker
    assert not any(t["tracker_id"] == tracker_id for t in list_b["trackers"])

    # Clean up auth context
    set_current_auth(None, None)


# -----------------------------------------------------------------------------
# 8. Defense-in-depth: resolve_effective_user_id() behavior
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolve_effective_user_id_requires_auth_when_configured():
    """When AUTH_REQUIRED is True and no user is authenticated, resolve_effective_user_id raises."""
    settings.AUTH_REQUIRED = True
    set_current_auth(None, None)

    with pytest.raises(PermissionError, match="Authentication required"):
        await resolve_effective_user_id()

    # Tool invocation returns cleanly formatted unauthorized error
    res = await list_trackers()
    assert res["status"] == "error"
    assert res["error"] == "unauthorized"

    # When auth is set, resolves cleanly
    dummy_uid = uuid.uuid4()
    set_current_auth(TokenPayload(sub="dummy"), dummy_uid)
    resolved = await resolve_effective_user_id()
    assert resolved == dummy_uid

    set_current_auth(None, None)
