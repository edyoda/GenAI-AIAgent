"""Resource-server side of auth: verify the JWTs issued by auth_server.

The MCP SDK does the HTTP part for us once we pass `token_verifier` + `AuthSettings`:
  - no / invalid token      -> 401 + WWW-Authenticate: Bearer ... resource_metadata="..."
  - missing required scope  -> 403 insufficient_scope
  - /.well-known/oauth-protected-resource/mcp  (tells clients which auth server to use)
We only have to answer "is this token valid, and what may it do?".
"""

from __future__ import annotations

import logging

import anyio
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError

from common.config import ISSUER, JWKS_URL, ResourceServer

log = logging.getLogger("mcp.auth")


class JwtTokenVerifier:
    """Checks RS256 signature (public key from the auth server's JWKS), exp, iss and aud."""

    def __init__(self, audience: str, issuer: str = ISSUER, jwks_url: str = JWKS_URL):
        self.audience = audience
        self.issuer = issuer
        # caches keys and re-fetches on an unknown `kid` (key rotation)
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # PyJWKClient is blocking (urllib); keep it off the event loop
            signing_key = await anyio.to_thread.run_sync(self._jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,  # token must be issued for THIS server
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWKClientConnectionError as e:
            log.warning("auth server unreachable, rejecting token: %s", e)
            return None
        except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
            log.info("rejected token: %s", e)
            return None

        return AccessToken(
            token=token,
            client_id=claims.get("client_id", claims["sub"]),
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            resource=self.audience,
            subject=claims["sub"],
            claims=claims,
        )


def auth_config(server: ResourceServer) -> dict:
    """kwargs for MCPServer(...) that turn on bearer-token auth for `server`."""
    return {
        "token_verifier": JwtTokenVerifier(audience=server.url),
        "auth": AuthSettings(
            issuer_url=ISSUER,
            resource_server_url=server.url,
            required_scopes=[server.required_scope],
            validate_token_resource=False,  # the verifier already checks `aud`
        ),
    }


def require_scope(scope: str) -> None:
    """Per-tool authorization, on top of the server-wide required scope."""
    token = get_access_token()
    if token is None or scope not in token.scopes:
        raise ToolError(f"Not authorized: this tool requires the '{scope}' scope.")
