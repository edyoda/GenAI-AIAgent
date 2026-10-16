"""Auth server token rules + resource-server 401/403 behaviour (no network: JWKS lookup is patched)."""

import time

import jwt
import pytest
from starlette.testclient import TestClient

from auth_server import app as auth_app
from common.config import ISSUER, RESOURCE_SERVERS

WEATHER = RESOURCE_SERVERS["weather"].url
SQL = RESOURCE_SERVERS["sql"].url
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def token_request(client_id, secret, resource=WEATHER, **extra):
    with TestClient(auth_app.app) as c:
        return c.post("/token", auth=(client_id, secret),
                      data={"grant_type": "client_credentials", "resource": resource, **extra})


# ---------------------------------------------------------------- auth server
def test_token_issued_with_audience_and_scope():
    r = token_request("demo-agent", "test-demo")
    assert r.status_code == 200
    claims = jwt.decode(r.json()["access_token"], auth_app.PRIVATE_KEY.public_key(), algorithms=["RS256"], audience=WEATHER)
    assert claims["iss"] == ISSUER and claims["scope"] == "weather:read" and claims["sub"] == "demo-agent"


@pytest.mark.parametrize("cid,secret,resource,data,status,error", [
    ("demo-agent", "wrong", WEATHER, {}, 401, "invalid_client"),
    ("nobody", "x", WEATHER, {}, 401, "invalid_client"),
    ("demo-agent", "test-demo", "http://evil/mcp", {}, 400, "invalid_target"),
    ("demo-agent", "test-demo", WEATHER, {"grant_type": "password"}, 400, "unsupported_grant_type"),
])
def test_token_errors(cid, secret, resource, data, status, error):
    r = token_request(cid, secret, resource, **data)
    assert r.status_code == status and r.json()["error"] == error


def test_scope_is_intersection():
    assert token_request("readonly-weather", "test-readonly", SQL).json()["scope"] == ""
    docs = RESOURCE_SERVERS["docs"].url
    assert token_request("docs-admin", "test-admin", docs).json()["scope"] == "docs:read docs:write"


# ---------------------------------------------------------------- resource server
def make_token(aud=WEATHER, scope="weather:read", iss=ISSUER, exp_in=300):
    now = int(time.time())
    return jwt.encode({"iss": iss, "sub": "t", "aud": aud, "scope": scope, "iat": now, "exp": now + exp_in},
                      auth_app.PRIVATE_KEY, algorithm="RS256", headers={"kid": auth_app.KID})


@pytest.fixture
def weather_client(monkeypatch):
    from weather_server.server import build_server

    mcp = build_server(auth=True)
    signing = type("K", (), {"key": auth_app.PRIVATE_KEY.public_key()})()
    monkeypatch.setattr(mcp._token_verifier._jwks, "get_signing_key_from_jwt", lambda _t: signing)
    with TestClient(mcp.streamable_http_app(host="127.0.0.1"), base_url="http://127.0.0.1:8001") as c:
        yield c


def post(client, token=None):
    headers = dict(HEADERS, **({"authorization": f"Bearer {token}"} if token else {}))
    return client.post("/mcp", json=INIT, headers=headers)


def test_valid_token_ok(weather_client):
    assert post(weather_client, make_token()).status_code == 200


@pytest.mark.parametrize("token", [
    None,
    "not-a-jwt",
    make_token(exp_in=-10),              # expired
    make_token(aud=SQL),                 # issued for another server
    make_token(iss="http://evil"),       # wrong issuer
])
def test_invalid_tokens_401(weather_client, token):
    r = post(weather_client, token)
    assert r.status_code == 401
    assert 'resource_metadata="' in r.headers["www-authenticate"]


def test_missing_scope_403(weather_client):
    r = post(weather_client, make_token(scope="docs:read"))
    assert r.status_code == 403 and "insufficient_scope" in r.headers["www-authenticate"]


def test_protected_resource_metadata(weather_client):
    meta = weather_client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert meta["resource"] == WEATHER and meta["authorization_servers"] == [ISSUER]
