"""Server-side entrypoint. Run from the repo root:

    uv run --project src/projects/mcp-demo/server python src/projects/mcp-demo/server/main.py <command>

Commands:
    setup                 seed the SQL database + build the document index (run once)
    all                   start auth + weather + docs + sql, each as its own process (Ctrl-C stops all)
    auth | weather | docs | sql     start one process
    token [--client C] [--server S] print a bearer token (for MCP Inspector); auth must be running
    seed-db | ingest      the two halves of `setup`
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so `common`, `*_server` import from any cwd

PROCESSES = ["auth", "weather", "docs", "sql"]
TOKENS_FILE = Path(__file__).resolve().parent / "tokens.json"


def run_one(name: str) -> None:
    if name == "auth":
        from auth_server.app import main
    elif name == "weather":
        from weather_server.server import main
    elif name == "docs":
        from docs_server.server import main
    else:
        from sql_server.server import main
    main()


def run_all() -> None:
    """One OS process per server, like separate deployments; this just supervises them."""
    procs = []
    for name in PROCESSES:
        procs.append(subprocess.Popen([sys.executable, "-u", __file__, name]))
        time.sleep(1.5 if name == "auth" else 0.3)  # resource servers fetch JWKS from auth lazily
    print("\nAll servers started. Ctrl-C to stop.\n", flush=True)
    reported: set[str] = set()
    try:
        try:
            save_tokens()
        except Exception as e:  # never let token saving take the servers down
            print(f"⚠ could not save tokens: {e}", flush=True)
        # servers are independent: if one dies, the others keep serving (clients degrade gracefully)
        while any(p.poll() is None for p in procs):
            for name, p in zip(PROCESSES, procs):
                if p.poll() is not None and name not in reported:
                    reported.add(name)
                    print(f"⚠ {name} server exited (code {p.returncode}); others keep running.", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # a 2nd Ctrl-C mustn't abort the clean shutdown
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def fetch_token(client_id: str, server: str) -> dict:
    """client_credentials token for one resource server, from the running auth server."""
    import httpx

    from common.config import CLIENTS, ISSUER, RESOURCE_SERVERS

    secret = CLIENTS[client_id]["secret"]
    if not secret:
        raise SystemExit(f"No secret configured for '{client_id}' in server/.env")
    try:
        r = httpx.post(f"{ISSUER}/token", auth=(client_id, secret), timeout=5, data={
            "grant_type": "client_credentials", "resource": RESOURCE_SERVERS[server].url})
    except httpx.ConnectError:
        raise SystemExit(f"Auth server not reachable at {ISSUER}. Start it first (`main.py auth` or `main.py all`).")
    if r.status_code != 200:
        raise SystemExit(f"Token request failed ({r.status_code}): {r.text}")
    return r.json()


def print_token(client_id: str, server: str) -> None:
    from common.config import RESOURCE_SERVERS

    body = fetch_token(client_id, server)
    print(f"# client={client_id}  server={server} ({RESOURCE_SERVERS[server].url})  "
          f"scope='{body['scope']}'  expires_in={body['expires_in']}s", file=sys.stderr)
    print(body["access_token"])


def save_tokens(client_id: str = "demo-agent") -> None:
    """Write a fresh token per MCP server to server/tokens.json (for Inspector / curl)."""
    import json

    from common.config import RESOURCE_SERVERS

    tokens = {}
    for name, rs in RESOURCE_SERVERS.items():
        try:
            body = fetch_token(client_id, name)
        except SystemExit as e:
            print(f"⚠ no token for {name}: {e}")
            continue
        tokens[name] = {"url": rs.url, "scope": body["scope"], "expires_in": body["expires_in"],
                        "access_token": body["access_token"]}
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    TOKENS_FILE.chmod(0o600)  # live credentials
    ttl = next(iter(tokens.values()))["expires_in"] if tokens else "?"
    print(f"🔑 {client_id} tokens for {', '.join(tokens) or 'no servers'} → {TOKENS_FILE} (expire in {ttl}s)\n",
          flush=True)


def main() -> None:
    from common.config import CLIENTS, RESOURCE_SERVERS

    parser = argparse.ArgumentParser(description="MCP demo servers")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in PROCESSES + ["all", "setup", "seed-db", "ingest"]:
        sub.add_parser(name)
    tok = sub.add_parser("token", help="print a bearer token for Inspector")
    tok.add_argument("--client", default="demo-agent", choices=list(CLIENTS))
    tok.add_argument("--server", default="weather", choices=list(RESOURCE_SERVERS))
    args = parser.parse_args()

    if args.cmd in PROCESSES:
        run_one(args.cmd)
    elif args.cmd == "all":
        run_all()
    elif args.cmd == "token":
        print_token(args.client, args.server)
    else:
        if args.cmd in ("setup", "seed-db"):
            from sql_server.seed_db import seed
            print("sales.db:", seed())
        if args.cmd in ("setup", "ingest"):
            from docs_server.store import ingest
            print("indexed chunks:", ingest())


if __name__ == "__main__":
    main()
