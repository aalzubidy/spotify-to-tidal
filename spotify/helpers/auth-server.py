#!/usr/bin/env python3
"""
Spotify OAuth2 Authorization Server

Starts a simple HTTP server on localhost:3030 to handle the Spotify
Authorization Code flow. Serves a login page, captures the callback,
exchanges the authorization code for tokens, and saves them.

Usage:
    python3 auth-server.py <CLIENT_ID> <CLIENT_SECRET> <DATA_DIR>
"""

import sys
import json
import time
import base64
import urllib.parse
import urllib.request
import http.server
import webbrowser
import os
from pathlib import Path

PORT = 3030
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"

SCOPES = " ".join([
    "user-library-read",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-follow-read",
    "user-top-read",
    "user-read-recently-played",
])

HTML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")


def build_auth_url(client_id):
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    })
    return f"https://accounts.spotify.com/authorize?{params}"


def verify_token(token_data, data_dir):
    """Make a quick API call to verify the access token works."""
    try:
        req = urllib.request.Request(
            "https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            user_data = json.loads(resp.read().decode())
            return user_data.get("id", None)
    except Exception:
        return None


def exchange_code_for_tokens(client_id, client_secret, code, data_dir):
    auth_header = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode()

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    with urllib.request.urlopen(req) as resp:
        token_data = json.loads(resp.read().decode())

    # Store when the token was obtained so we can check expiry
    token_data["obtained_at"] = int(time.time())

    tokens_path = os.path.join(data_dir, "spotify-tokens.json")
    os.makedirs(data_dir, exist_ok=True)
    with open(tokens_path, "w") as f:
        json.dump(token_data, f, indent=2)

    return token_data


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handles HTTP requests for the auth flow."""

    client_id = None
    client_secret = None
    data_dir = None
    auth_result = None

    def log_message(self, fmt, *args):
        # Suppress default logging to stderr
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/authorize":
            self._serve_authorize_page()
        elif parsed.path == "/callback":
            self._handle_callback(parsed.query)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def _serve_authorize_page(self):
        html_path = os.path.join(HTML_DIR, "authorize.html")
        if os.path.exists(html_path):
            with open(html_path, "r") as f:
                content = f.read()
            content = content.replace("{{AUTH_URL}}", build_auth_url(self.client_id))
            content = content.replace("{{CLIENT_ID}}", self.client_id[:8] + "...")
        else:
            content = f"""<!DOCTYPE html>
<html><body>
<h1>Spotify Authorization</h1>
<p><a href="{build_auth_url(self.client_id)}">Login with Spotify</a></p>
</body></html>"""

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _handle_callback(self, query_string):
        params = urllib.parse.parse_qs(query_string)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]

        html_path = os.path.join(HTML_DIR, "callback.html")

        if error:
            content = f"""<!DOCTYPE html>
<html><body>
<h1>Authorization Failed</h1>
<p>Error: {error}</p>
</body></html>"""
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
            CallbackHandler.auth_result = {"error": error}
            return

        if not code:
            content = """<!DOCTYPE html>
<html><body>
<h1>Authorization Failed</h1>
<p>No authorization code received.</p>
</body></html>"""
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
            CallbackHandler.auth_result = {"error": "no_code"}
            return

        try:
            token_data = exchange_code_for_tokens(
                self.client_id, self.client_secret, code, self.data_dir
            )
            CallbackHandler.auth_result = {"success": True, "token_data": token_data}

            if os.path.exists(html_path):
                with open(html_path, "r") as f:
                    content = f.read()
                content = content.replace(
                    "{{TOKENS_PATH}}",
                    os.path.join(self.data_dir, "spotify-tokens.json"),
                )
            else:
                content = f"""<!DOCTYPE html>
<html><body>
<h1>Authorization Successful!</h1>
<p>Tokens saved to: {os.path.join(self.data_dir, 'spotify-tokens.json')}</p>
<p>You can close this window and return to the terminal.</p>
</body></html>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        except Exception as e:
            content = f"""<!DOCTYPE html>
<html><body>
<h1>Token Exchange Failed</h1>
<p>{str(e)}</p>
</body></html>"""
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
            CallbackHandler.auth_result = {"error": str(e)}

    def do_POST(self):
        self.do_GET()


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <CLIENT_ID> <CLIENT_SECRET> <DATA_DIR>", file=sys.stderr)
        sys.exit(1)

    client_id = sys.argv[1]
    client_secret = sys.argv[2]
    data_dir = sys.argv[3]

    # Set class-level attributes for the handler
    CallbackHandler.client_id = client_id
    CallbackHandler.client_secret = client_secret
    CallbackHandler.data_dir = data_dir

    server = http.server.HTTPServer(("127.0.0.1", PORT), CallbackHandler)
    auth_url = build_auth_url(client_id)

    print(f"\n{'='*60}")
    print(f"  Spotify Authorization Server")
    print(f"  Listening on: http://127.0.0.1:{PORT}")
    print(f"{'='*60}")
    print(f"\n  Opening browser for Spotify login...")
    print(f"  If the browser doesn't open, visit:\n")
    print(f"  {auth_url}\n")

    # Open browser after a short delay to let the server start
    webbrowser.open(auth_url)

    # Handle one request (the callback), then exit
    server.handle_request()

    result = CallbackHandler.auth_result
    if result and result.get("success"):
        token_path = os.path.join(data_dir, "spotify-tokens.json")
        # Verify the token works by making a test API call
        user_id = verify_token(result["token_data"], data_dir)
        if user_id:
            print(f"\n  ✅ Authorization successful!")
            print(f"  Logged in as Spotify user: {user_id}")
            print(f"  Tokens saved to: {token_path}\n")
        else:
            print(f"\n  ⚠️  Token saved but verification API call failed.", file=sys.stderr)
            print(f"  The token may be invalid or network may be unavailable.", file=sys.stderr)
            print(f"  File: {token_path}\n")
            sys.exit(1)
    else:
        error = result.get("error", "Unknown error") if result else "No response"
        print(f"\n  ❌ Authorization failed: {error}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()