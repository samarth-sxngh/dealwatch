"""JWT and JWKS token verification for OAuth 2.1."""

import logging
from typing import Any

import jwt
from jwt import PyJWKClient

from app.auth.models import TokenPayload
from app.config import settings

logger = logging.getLogger(__name__)


class TokenVerificationError(ValueError):
    """Raised when JWT verification fails."""


class JWKSVerifier:
    """Verifies JWT tokens against a remote JWKS endpoint with caching and algorithms validation."""

    def __init__(
        self,
        jwks_url: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        algorithms: list[str] | None = None,
        cache_jwk_set: bool = True,
        lifespan: int = 3600,
        test_secret: str | None = None,
    ) -> None:
        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms or ["RS256", "ES256", "HS256"]
        self.cache_jwk_set = cache_jwk_set
        self.lifespan = lifespan
        self.test_secret = test_secret
        self.jwks_client: PyJWKClient | None = None

        initial_jwks = self.jwks_url or settings.AUTH_JWKS_URL
        if initial_jwks:
            self.jwks_client = PyJWKClient(
                initial_jwks,
                cache_jwk_set=cache_jwk_set,
                lifespan=lifespan,
            )

    def verify_token(self, token: str, test_secret: str | None = None) -> TokenPayload:
        """Verifies and decodes a JWT token.

        Args:
            token: The raw Bearer JWT token string.
            test_secret: Optional symmetric secret (for unit/integration testing with HS256).

        Returns:
            TokenPayload with validated claims.

        Raises:
            TokenVerificationError: If token is expired, signature is invalid, or claims mismatch.
        """
        if not token:
            raise TokenVerificationError("Token string cannot be empty.")

        effective_secret = test_secret or self.test_secret or settings.AUTH_TEST_SECRET
        effective_issuer = self.issuer or settings.AUTH_ISSUER
        effective_audience = self.audience or settings.AUTH_AUDIENCE
        effective_jwks_url = self.jwks_url or settings.AUTH_JWKS_URL

        try:
            # 1. Test secret symmetric path (for testing / development)
            if effective_secret:
                payload = jwt.decode(
                    token,
                    effective_secret,
                    algorithms=["HS256"],
                    audience=effective_audience,
                    issuer=effective_issuer,
                    options={
                        "verify_exp": True,
                        "verify_aud": bool(effective_audience),
                        "verify_iss": bool(effective_issuer),
                    },
                )
            # 2. Remote JWKS asymmetric path (Descope / WorkOS / Stytch)
            else:
                if not self.jwks_client and effective_jwks_url:
                    self.jwks_client = PyJWKClient(
                        effective_jwks_url,
                        cache_jwk_set=self.cache_jwk_set,
                        lifespan=self.lifespan,
                    )

                if self.jwks_client:
                    signing_key = self.jwks_client.get_signing_key_from_jwt(token)
                    payload = jwt.decode(
                        token,
                        signing_key.key,
                        algorithms=self.algorithms,
                        audience=effective_audience,
                        issuer=effective_issuer,
                        options={
                            "verify_exp": True,
                            "verify_aud": bool(effective_audience),
                            "verify_iss": bool(effective_issuer),
                        },
                    )
                else:
                    raise TokenVerificationError(
                        "No JWKS URL configured (AUTH_JWKS_URL is empty) to verify bearer token."
                    )

            # 3. Extract scopes
            scopes = self._extract_scopes(payload)

            sub = str(payload.get("sub", ""))
            if not sub:
                raise TokenVerificationError("Token missing mandatory 'sub' claim.")

            email = payload.get("email")
            if isinstance(email, str):
                email = email.lower().strip()
            else:
                email = None

            return TokenPayload(
                sub=sub,
                email=email,
                scopes=scopes,
                iss=payload.get("iss"),
                aud=payload.get("aud"),
                exp=payload.get("exp"),
                raw_claims=payload,
            )

        except jwt.ExpiredSignatureError as e:
            logger.warning("Token expired: %s", e)
            raise TokenVerificationError("Token has expired.") from e
        except jwt.InvalidAudienceError as e:
            logger.warning("Invalid audience: %s", e)
            raise TokenVerificationError("Invalid token audience.") from e
        except jwt.InvalidIssuerError as e:
            logger.warning("Invalid issuer: %s", e)
            raise TokenVerificationError("Invalid token issuer.") from e
        except jwt.PyJWTError as e:
            logger.warning("JWT verification error: %s", e)
            raise TokenVerificationError(f"Invalid token: {e}") from e
        except Exception as e:
            logger.exception("Unexpected error during token verification")
            raise TokenVerificationError(f"Token verification failed: {e}") from e

    def _extract_scopes(self, payload: dict[str, Any]) -> list[str]:
        """Extracts scopes from standard scope, scp, or permissions claims."""
        if "scope" in payload and isinstance(payload["scope"], str):
            return [s.strip() for s in payload["scope"].split() if s.strip()]
        if "scp" in payload and isinstance(payload["scp"], list):
            return [str(s).strip() for s in payload["scp"] if str(s).strip()]
        if "permissions" in payload and isinstance(payload["permissions"], list):
            return [str(s).strip() for s in payload["permissions"] if str(s).strip()]
        return []


token_verifier = JWKSVerifier()
