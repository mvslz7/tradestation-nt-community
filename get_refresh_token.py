#!/usr/bin/env python3
"""
Obtain a TradeStation OAuth refresh token via the Authorization Code flow.

Starts a local HTTP server on port 3000 to capture the redirect, opens
a browser for login, then exchanges the code for tokens.

Prerequisites
-------------
1. Create an app at https://developer.tradestation.com/
2. Add ``http://localhost:3000`` as a Redirect URI in your app settings.
3. Set TRADESTATION_CLIENT_ID and TRADESTATION_CLIENT_SECRET (or enter
   them when prompted).

Usage
-----
    python get_refresh_token.py

Then set the printed token:
    export TRADESTATION_REFRESH_TOKEN="<token>"
"""

import http.server
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

_AUTH_URL = "https://signin.tradestation.com/authorize"
_TOKEN_URL = "https://signin.tradestation.com/oauth/token"
_REDIRECT_PORT = 3000
_REDIRECT_URI = f"http://localhost:{_REDIRECT_PORT}"
_SCOPES = "openid profile offline_access MarketData ReadAccount Trade OptionSpreads"


def _exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": _REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"\n❌ Token exchange failed (HTTP {e.code}): {body}")
        sys.exit(1)


def main() -> None:
    client_id = os.getenv("TRADESTATION_CLIENT_ID") or input("Client ID: ").strip()
    client_secret = os.getenv("TRADESTATION_CLIENT_SECRET") or input("Client Secret: ").strip()
    if not client_id or not client_secret:
        print("❌ Client ID and Client Secret are required.")
        sys.exit(1)

    auth_params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "audience": "https://api.tradestation.com",
        "scope": _SCOPES,
    })
    auth_url = f"{_AUTH_URL}?{auth_params}"

    # One-shot handler that captures the auth code from the redirect.
    result: dict = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs:
                result["code"] = qs["code"][0]
                body = b"<h2>Authorization successful - you can close this tab.</h2>"
                self.send_response(200)
            elif "error" in qs:
                err = qs.get("error", ["unknown"])[0]
                desc = qs.get("error_description", [""])[0]
                result["error"] = f"{err}: {desc}"
                body = f"<h2>Error: {err} — {desc}</h2>".encode()
                self.send_response(400)
            else:
                body = b"<h2>Unexpected request.</h2>"
                self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            pass  # suppress access log noise

    try:
        server = http.server.HTTPServer(("localhost", _REDIRECT_PORT), _Handler)
    except OSError as e:
        print(f"❌ Could not bind to port {_REDIRECT_PORT}: {e}")
        print(f"   Kill whatever is using that port, or change _REDIRECT_PORT in this script")
        print(f"   (and update your app's Redirect URI to match).")
        sys.exit(1)

    print(f"\nOpening browser for TradeStation login ...")
    print(f"If the browser does not open, visit:\n\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Block until the browser hits our server.
    server.handle_request()
    server.server_close()

    if "error" in result:
        print(f"\n❌ Authorization failed: {result['error']}")
        sys.exit(1)
    if "code" not in result:
        print("\n❌ No authorization code received.")
        sys.exit(1)

    print("✅ Code received — exchanging for tokens ...")
    tokens = _exchange_code(client_id, client_secret, result["code"])

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token", "")

    if not refresh_token:
        print("\n❌ No refresh_token in response.")
        print("   Make sure 'offline_access' scope is enabled for your app in the TS developer portal.")
        print(f"   Full response: {tokens}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Refresh Token:")
    print(f"  {refresh_token}")
    print()
    print("Access Token (valid ~20 min):")
    print(f"  {access_token}")
    print()
    print("Export for use:")
    print(f'  export TRADESTATION_REFRESH_TOKEN="{refresh_token}"')
    print("=" * 60)


if __name__ == "__main__":
    main()
