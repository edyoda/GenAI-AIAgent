"""Client-side auth: OAuth client_credentials tokens, one per MCP server (resource).

`TokenManager` is an `httpx.Auth`, so every HTTP request the MCP transport sends gets a
bearer token automatically:
  - no token yet or it expires within `refresh_margin` s  -> fetch a new one first
  - server answers 401 (expired / key rotated / revoked)  -> refresh once and replay the request
  - server answers 403 (insufficient_scope)                -> NOT retried; a new token has the same scopes
"""

from __future__ import annotations

import asyncio
import time

import httpx


class AuthError(Exception):
    """The auth server refused to issue a token (bad credentials, unknown resource, down)."""


class TokenManager(httpx.Auth):
    def __init__(self, token_url: str, client_id: str, client_secret: str, resource: str,
                 refresh_margin: int = 30):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.resource = resource  # RFC 8707: the token's `aud`, i.e. which MCP server it is for
        self.refresh_margin = refresh_margin
        self.scope = ""           # scopes actually granted (shown by /servers)
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock: asyncio.Lock | None = None
        self.refreshes = 0

    # ------------------------------------------------------------------ token fetch
    async def get_token(self, force: bool = False) -> str:
        self._lock = self._lock or asyncio.Lock()
        async with self._lock:  # concurrent tool calls share one refresh
            if force or not self._token or time.time() >= self._expires_at - self.refresh_margin:
                await self._fetch()
            return self._token  # type: ignore[return-value]

    async def _fetch(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.post(self.token_url, auth=(self.client_id, self.client_secret),
                                    data={"grant_type": "client_credentials", "resource": self.resource})
        except httpx.HTTPError as e:
            raise AuthError(f"auth server unreachable at {self.token_url}: {e}") from e
        if r.status_code != 200:
            try:
                err = r.json()
                detail = f"{err.get('error')}: {err.get('error_description')}"
            except ValueError:
                detail = r.text[:200]
            raise AuthError(f"token request refused ({r.status_code}) — {detail}")
        body = r.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 300))
        self.scope = body.get("scope", "")
        self.refreshes += 1

    # ------------------------------------------------------------------ httpx.Auth hook
    async def async_auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {await self.get_token()}"
        response = yield request
        if response.status_code == 401:
            request.headers["Authorization"] = f"Bearer {await self.get_token(force=True)}"
            yield request

    def sync_auth_flow(self, request: httpx.Request):  # MCP transports are async-only
        raise RuntimeError("TokenManager supports async clients only")
