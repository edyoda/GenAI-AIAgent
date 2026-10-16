"""Minimal OAuth 2.1 authorization server for the demo (client_credentials grant only).

    POST /token                                   -> signed RS256 JWT access token
    GET  /.well-known/jwks.json                   -> public key(s); resource servers verify with these
    GET  /.well-known/oauth-authorization-server  -> RFC 8414 metadata
    GET  /health

Tokens are bound to ONE resource server via the RFC 8707 `resource` parameter: `aud` is that
server's URL and `scope` is (requested ∩ client's allowed ∩ server's scopes). A token for the
weather server is useless at the sql server, and vice versa.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from common.config import CLIENTS, ISSUER, KEYS_DIR, RESOURCE_SERVERS, TOKEN_TTL_SECONDS

PRIVATE_KEY_FILE = KEYS_DIR / "private.pem"


# --------------------------------------------------------------------------- #
# Signing key (generated once, kept in the gitignored server/.keys/)
# --------------------------------------------------------------------------- #
def load_or_create_key() -> rsa.RSAPrivateKey:
    if PRIVATE_KEY_FILE.exists():
        return serialization.load_pem_private_key(PRIVATE_KEY_FILE.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    KEYS_DIR.mkdir(exist_ok=True)
    PRIVATE_KEY_FILE.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    PRIVATE_KEY_FILE.chmod(0o600)
    return key


PRIVATE_KEY = load_or_create_key()
_public_der = PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
KID = base64.urlsafe_b64encode(hashlib.sha256(_public_der).digest()[:12]).decode().rstrip("=")
RESOURCES = {s.url: s for s in RESOURCE_SERVERS.values()}


def issue_token(client_id: str, resource: str, scopes: list[str]) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": client_id,
        "client_id": client_id,
        "aud": resource,
        "scope": " ".join(scopes),
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})


def grant(client_id: str, resource: str, requested: list[str] | None) -> list[str]:
    """Scopes the client actually gets for this resource (may be empty -> 403 at the server)."""
    allowed = set(CLIENTS[client_id]["scopes"]) & set(RESOURCES[resource].scopes)
    return sorted(allowed & set(requested) if requested else allowed)


def _error(status: int, error: str, description: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Basic"} if status == 401 else None
    return JSONResponse({"error": error, "error_description": description}, status, headers=headers)


def _client_credentials(request: Request, form) -> tuple[str | None, str | None]:
    """client_secret_basic (Authorization: Basic) or client_secret_post (form fields)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            cid, _, secret = base64.b64decode(header[6:]).decode().partition(":")
            return cid, secret
        except Exception:
            return None, None
    return form.get("client_id"), form.get("client_secret")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
async def token_endpoint(request: Request) -> JSONResponse:
    form = await request.form()
    if form.get("grant_type") != "client_credentials":
        return _error(400, "unsupported_grant_type", "Only client_credentials is supported.")

    client_id, secret = _client_credentials(request, form)
    client = CLIENTS.get(client_id or "")
    if not client or not client["secret"] or not hmac.compare_digest(secret or "", client["secret"]):
        return _error(401, "invalid_client", "Unknown client or wrong secret.")

    resource = form.get("resource")
    if resource not in RESOURCES:
        return _error(400, "invalid_target", f"'resource' must be one of: {sorted(RESOURCES)}")

    requested = form.get("scope", "").split() or None
    scopes = grant(client_id, resource, requested)
    return JSONResponse({
        "access_token": issue_token(client_id, resource, scopes),
        "token_type": "Bearer",
        "expires_in": TOKEN_TTL_SECONDS,
        "scope": " ".join(scopes),
    }, headers={"Cache-Control": "no-store"})


async def jwks(_: Request) -> JSONResponse:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True)
    return JSONResponse({"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]})


async def metadata(_: Request) -> JSONResponse:
    return JSONResponse({
        "issuer": ISSUER,
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        "grant_types_supported": ["client_credentials"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "scopes_supported": sorted({s for r in RESOURCES.values() for s in r.scopes}),
    })


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "auth"})


app = Starlette(routes=[
    Route("/token", token_endpoint, methods=["POST"]),
    Route("/.well-known/jwks.json", jwks),
    Route("/.well-known/oauth-authorization-server", metadata),
    Route("/health", health),
])


def main() -> None:
    import uvicorn

    from common.config import AUTH_PORT, HOST

    enabled = [c for c, v in CLIENTS.items() if v["secret"]]
    print(f"auth server → {ISSUER}  (clients enabled: {', '.join(enabled) or 'NONE — set secrets in .env'})")
    uvicorn.run(app, host=HOST, port=AUTH_PORT, log_level="warning")
