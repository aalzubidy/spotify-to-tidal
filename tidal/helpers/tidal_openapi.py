#!/usr/bin/env python3
"""
Official TIDAL v2 API client — openapi.tidal.com/v2

Used for the MATCHING phase only (read-only catalog lookups):
  * Exact ISRC -> Tidal track:   GET /tracks?filter[isrc]=...
  * Exact UPC  -> Tidal album:   GET /albums?filter[barcodeId]=...
  * Text fallback:               GET /searchResults/{query}/relationships/tracks

Why this exists: the old internal api.tidal.com/v1 path has no ISRC filter,
which forced fragile fuzzy album matching. The official v2 API supports exact
ISRC/barcode lookup in *batches*, so thousands of tracks resolve in a few
hundred requests instead of thousands of fuzzy searches. This single client now
handles BOTH matching (read) and import (write) — the v1 path is retired.

Auth: Authorization Code + PKCE against the user's own registered TIDAL app
(client id/secret in the working-dir .env, redirect http://localhost:3030/callback).
client_credentials is intentionally NOT used — TIDAL disables it for most apps,
and catalog reads still require a user token.

CLI:
    python3 tidal_openapi.py <WORK_DIR> auth          # one-time browser PKCE login
    python3 tidal_openapi.py <WORK_DIR> probe <ISRC>  # sanity-check a lookup
"""

import sys
import os
import json
import time
import base64
import hashlib
import secrets
import threading
import urllib.parse
import http.server

import requests

# Official API endpoints
LOGIN_BASE = "https://login.tidal.com"
AUTH_BASE = "https://auth.tidal.com/v1/oauth2"
API_BASE = "https://openapi.tidal.com/v2"
JSONAPI_ACCEPT = "application/vnd.api+json"

# Local callback (must match a redirect URI registered on the TIDAL app).
# Override with TIDAL_REDIRECT_URI in the .env if you registered a different one
# (e.g. http://127.0.0.1:3030/callback). The port is parsed from this URI.
CALLBACK_PORT = 3030
DEFAULT_REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"

# Scopes — request everything the migration could need; the app grants what it has.
SCOPES = "user.read collection.read collection.write playlists.read playlists.write search.read"

# Conservative steady pacing. The official API rate limit is not publicly fixed;
# a single matching pass is only a few hundred requests, so a gentle steady rate
# avoids 429s entirely. Tune via TIDAL_OPENAPI_MIN_INTERVAL in the .env if needed.
DEFAULT_MIN_INTERVAL = 0.12  # seconds between requests (~8 req/s)

SESSION_FILENAME = "tidal-openapi-session.json"


# Environment / credentials

def load_env(work_dir: str) -> dict:
    """Parse the working-dir spotify-to-tidal.env into a dict (no external deps)."""
    path = os.path.join(work_dir, "spotify-to-tidal.env")
    env = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # Allow real environment variables to override the file
    for k in ("TIDAL_CLIENT_ID", "TIDAL_CLIENT_SECRET", "TIDAL_OPENAPI_MIN_INTERVAL",
              "TIDAL_REDIRECT_URI"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


# PKCE helpers

def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


def _decode_jwt_payload(token: str) -> dict:
    """Decode a JWT payload WITHOUT verifying (only to read the user id / country)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode())
    except Exception:
        return {}


# Rate limiter — steady pacing, thread-safe

class _RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self.min_interval


# Client

class TidalOpenAPI:
    def __init__(self, work_dir: str):
        self.work_dir = work_dir
        self.session_path = os.path.join(work_dir, SESSION_FILENAME)
        self.env = load_env(work_dir)
        self.client_id = self.env.get("TIDAL_CLIENT_ID")
        self.client_secret = self.env.get("TIDAL_CLIENT_SECRET")
        if not self.client_id:
            raise RuntimeError("TIDAL_CLIENT_ID missing from spotify-to-tidal.env")
        try:
            interval = float(self.env.get("TIDAL_OPENAPI_MIN_INTERVAL", DEFAULT_MIN_INTERVAL))
        except ValueError:
            interval = DEFAULT_MIN_INTERVAL
        self.limiter = _RateLimiter(interval)
        self.redirect_uri = self.env.get("TIDAL_REDIRECT_URI", DEFAULT_REDIRECT_URI)
        parsed_port = urllib.parse.urlparse(self.redirect_uri).port
        self.callback_port = parsed_port or CALLBACK_PORT
        self.session = self._load_session()
        self._http = requests.Session()

    # session persistence

    def _load_session(self):
        if os.path.exists(self.session_path):
            return json.load(open(self.session_path))
        return None

    def _save_session(self):
        with open(self.session_path, "w") as f:
            json.dump(self.session, f, indent=2)

    def is_authenticated(self) -> bool:
        if not self.session:
            return False
        if self.session.get("refresh_token"):
            return True
        # No refresh token (some app tiers omit it) — accept a non-expired access token
        if self.session.get("access_token"):
            obtained = self.session.get("obtained_at", 0)
            expires_in = self.session.get("expires_in", 3600)
            return (time.time() - obtained) < (expires_in - 60)
        return False

    def country(self, default="US") -> str:
        if self.session and self.session.get("country_code"):
            return self.session["country_code"]
        return default

    # PKCE auth

    def authenticate(self):
        """Run the Authorization Code + PKCE flow via a local callback server."""
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        params = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        })
        auth_url = f"{LOGIN_BASE}/authorize?{params}"

        holder = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404); self.end_headers(); return
                q = urllib.parse.parse_qs(parsed.query)
                holder["code"] = q.get("code", [None])[0]
                holder["state"] = q.get("state", [None])[0]
                holder["error"] = q.get("error", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                ok = holder.get("code") and not holder.get("error")
                msg = ("Authorization successful. You can close this tab and return "
                       "to the terminal.") if ok else f"Authorization failed: {holder.get('error')}"
                self.wfile.write(f"<!doctype html><html><body style='font-family:sans-serif'>"
                                 f"<h2>TIDAL</h2><p>{msg}</p></body></html>".encode())

        print("=" * 60)
        print("  TIDAL Official API — Authorization (PKCE)")
        print("=" * 60)
        print("\n  Open this URL in your browser and approve access:\n")
        print(f"  {auth_url}\n")
        print(f"  Waiting for the redirect to {self.redirect_uri} ...")

        server = http.server.HTTPServer(("127.0.0.1", self.callback_port), Handler)
        try:
            import webbrowser
            webbrowser.open(auth_url)
        except Exception:
            pass
        server.handle_request()  # serve exactly one request (the callback)
        server.server_close()

        if holder.get("error") or not holder.get("code"):
            raise RuntimeError(f"Authorization failed: {holder.get('error') or 'no code received'}")
        if holder.get("state") != state:
            raise RuntimeError("State mismatch — possible CSRF; aborting.")

        token = self._exchange_code(holder["code"], verifier)
        self._store_token(token)
        print(f"\n  Authorized. user_id={self.session.get('user_id')} "
              f"country={self.session.get('country_code')}")
        print(f"  Session saved to: {self.session_path}")

    def _token_auth(self):
        """Basic auth header tuple if a client secret is configured, else None."""
        if self.client_secret:
            return (self.client_id, self.client_secret)
        return None

    def _exchange_code(self, code: str, verifier: str) -> dict:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        resp = requests.post(f"{AUTH_BASE}/token", data=data, auth=self._token_auth(), timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def _store_token(self, token: dict):
        access = token["access_token"]
        claims = _decode_jwt_payload(access)
        user_id = ""
        user = token.get("user") or {}
        if isinstance(user, dict):
            user_id = str(user.get("userId", "") or "")
        if not user_id:
            user_id = str(claims.get("uid", claims.get("sub", "")) or "")
        country = ""
        if isinstance(user, dict):
            country = user.get("countryCode", "") or ""
        country = country or claims.get("countryCode", "") or self.country()
        self.session = {
            "access_token": access,
            "refresh_token": token.get("refresh_token", self.session.get("refresh_token") if self.session else ""),
            "expires_in": token.get("expires_in", 3600),
            "obtained_at": int(time.time()),
            "user_id": user_id,
            "country_code": country,
        }
        self._save_session()

    def _refresh(self):
        if not self.session or not self.session.get("refresh_token"):
            # No refresh token — if the access token is still valid, just continue
            if self.session and self.session.get("access_token"):
                obtained = self.session.get("obtained_at", 0)
                expires_in = self.session.get("expires_in", 3600)
                if (time.time() - obtained) < (expires_in - 60):
                    return  # still valid, nothing to do
            raise RuntimeError("Token expired and no refresh token — run: tidal_openapi.py <WORK_DIR> auth")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.session["refresh_token"],
            "client_id": self.client_id,
        }
        resp = requests.post(f"{AUTH_BASE}/token", data=data, auth=self._token_auth(), timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.text[:300]} "
                               f"(re-run: tidal_openapi.py <WORK_DIR> auth)")
        self._store_token(resp.json())

    def _ensure_token(self):
        if not self.session:
            raise RuntimeError("Not authenticated — run: tidal_openapi.py <WORK_DIR> auth")
        expires_at = self.session.get("obtained_at", 0) + self.session.get("expires_in", 0)
        if time.time() > expires_at - 120:
            self._refresh()

    # core request with rate limiting + Retry-After

    def _get(self, path: str, params=None, retries: int = 6):
        self._ensure_token()
        url = f"{API_BASE}{path}"
        for attempt in range(retries):
            self.limiter.wait()
            headers = {
                "Authorization": f"Bearer {self.session['access_token']}",
                "Accept": JSONAPI_ACCEPT,
            }
            try:
                resp = self._http.get(url, headers=headers, params=params, timeout=30)
            except requests.exceptions.RequestException:
                if attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                return None
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "0") or 0) or min(2 ** attempt, 30)
                print(f"    429 rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                self._refresh()
                continue
            if resp.status_code in (404,):
                return {"data": []}
            if resp.status_code >= 500:
                if attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                return None
            if resp.status_code >= 400:
                return None
            txt = resp.text.strip()
            return resp.json() if txt else {"data": []}
        return None

    # JSON:API param encoding — repeated filter[isrc]=A&filter[isrc]=B

    @staticmethod
    def _filter_params(field: str, values, country: str, include=None):
        params = [("countryCode", country)]
        for v in values:
            params.append((f"filter[{field}]", v))
        if include:
            params.append(("include", include))
        return params

    # Matching methods

    def tracks_by_isrc(self, isrcs, country=None, include="albums,artists") -> dict:
        """Batch-resolve ISRCs. Returns {ISRC_UPPER: {tidal_id, title, album_id, artist_ids}}.

        `isrcs` should be a small batch (<= max supported per request). The caller
        handles batching and the overall progress/cache.
        """
        country = country or self.country()
        params = self._filter_params("isrc", isrcs, country, include)
        body = self._get("/tracks", params)
        out = {}
        if not body or not isinstance(body, dict):
            return out
        # Map included album/artist resource ids are already the relationship ids.
        for item in body.get("data", []):
            attrs = item.get("attributes", {}) or {}
            isrc = (attrs.get("isrc") or "").upper().strip()
            if not isrc:
                continue
            rel = item.get("relationships", {}) or {}
            album_id = None
            adata = rel.get("albums", {}).get("data")
            if isinstance(adata, list) and adata:
                album_id = str(adata[0].get("id"))
            elif isinstance(adata, dict):
                album_id = str(adata.get("id"))
            artist_ids = []
            ardata = rel.get("artists", {}).get("data")
            if isinstance(ardata, list):
                artist_ids = [str(a.get("id")) for a in ardata if a.get("id")]
            elif isinstance(ardata, dict) and ardata.get("id"):
                artist_ids = [str(ardata["id"])]
            # First hit per ISRC wins (re-releases share ISRC); keep first seen.
            if isrc not in out:
                out[isrc] = {
                    "tidal_id": str(item.get("id")),
                    "title": attrs.get("title", ""),
                    "album_id": album_id,
                    "artist_ids": artist_ids,
                }
        return out

    def albums_by_barcode(self, barcodes, country=None) -> dict:
        """Batch-resolve UPC barcodes. Returns {BARCODE: {tidal_album_id, title}}."""
        country = country or self.country()
        params = self._filter_params("barcodeId", barcodes, country)
        body = self._get("/albums", params)
        out = {}
        if not body or not isinstance(body, dict):
            return out
        for item in body.get("data", []):
            attrs = item.get("attributes", {}) or {}
            bc = (attrs.get("barcodeId") or "").strip()
            if bc and bc not in out:
                out[bc] = {"tidal_album_id": str(item.get("id")), "title": attrs.get("title", "")}
        return out

    # Paginated reads (verification / dedup)

    def _get_paginated(self, path: str, params):
        """Follow JSON:API cursor pagination. Yields each `data` item dict."""
        params = list(params or [])
        cursor = None
        while True:
            p = list(params)
            if cursor:
                p.append(("page[cursor]", cursor))
            body = self._get(path, p)
            if not body or not isinstance(body, dict):
                return
            for item in body.get("data", []):
                yield item
            nxt = (body.get("links") or {}).get("next")
            if not nxt:
                return
            q = urllib.parse.urlparse(nxt).query
            cursor = urllib.parse.parse_qs(q).get("page[cursor]", [None])[0]
            if not cursor:
                return

    def get_collection_ids(self, kind: str) -> set:
        """kind in {tracks, albums, artists}. Returns set of Tidal IDs in the user's collection."""
        uid = self.user_collection_id()
        if not uid:
            return set()
        ids = set()
        for item in self._get_paginated(
                f"/userCollections/{uid}/relationships/{kind}",
                [("countryCode", self.country())]):
            if item.get("id"):
                ids.add(str(item["id"]))
        return ids

    def get_user_playlists(self) -> list:
        """Returns [{id, name}] of playlists in the user's collection."""
        uid = self.user_collection_id()
        if not uid:
            return []
        path = f"/userCollections/{uid}/relationships/playlists"
        base_params = [("countryCode", self.country()), ("include", "playlists")]
        ids = []
        names = {}
        cursor = None
        while True:
            p = list(base_params)
            if cursor:
                p.append(("page[cursor]", cursor))
            body = self._get(path, p)
            if not body or not isinstance(body, dict):
                break
            for item in body.get("data", []):
                if item.get("id"):
                    ids.append(str(item["id"]))
            # collect names from included on every page
            for inc in body.get("included", []):
                if inc.get("type") == "playlists":
                    names[str(inc["id"])] = (inc.get("attributes") or {}).get("name", "")
            nxt = (body.get("links") or {}).get("next")
            if not nxt:
                break
            q = urllib.parse.urlparse(nxt).query
            cursor = urllib.parse.parse_qs(q).get("page[cursor]", [None])[0]
            if not cursor:
                break
        return [{"id": pid, "name": names.get(pid, "")} for pid in ids]

    def get_playlist_item_ids(self, playlist_id: str) -> list:
        """Returns ordered list of track IDs in a playlist."""
        ids = []
        for item in self._get_paginated(
                f"/playlists/{playlist_id}/relationships/items",
                [("countryCode", self.country())]):
            if item.get("type") == "tracks" and item.get("id"):
                ids.append(str(item["id"]))
        return ids

    # Write helpers (full-v2 import path)

    def _post(self, path: str, body: dict, params=None, retries: int = 6):
        """POST JSON:API body. Returns (ok: bool, status: int, parsed_or_text)."""
        self._ensure_token()
        url = f"{API_BASE}{path}"
        for attempt in range(retries):
            self.limiter.wait()
            headers = {
                "Authorization": f"Bearer {self.session['access_token']}",
                "Accept": JSONAPI_ACCEPT,
                "Content-Type": JSONAPI_ACCEPT,
            }
            try:
                resp = self._http.post(url, headers=headers, params=params,
                                       data=json.dumps(body), timeout=30)
            except requests.exceptions.RequestException:
                if attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                return False, 0, "network error"
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "0") or 0) or min(2 ** attempt, 30)
                print(f"    429 rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                self._refresh()
                continue
            if resp.status_code >= 500:
                if attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                return False, resp.status_code, resp.text[:300]
            txt = resp.text.strip()
            parsed = None
            if txt:
                try:
                    parsed = resp.json()
                except ValueError:
                    parsed = txt
            ok = 200 <= resp.status_code < 300
            return ok, resp.status_code, parsed
        return False, 0, "exhausted retries"

    def user_collection_id(self) -> str:
        return str(self.session.get("user_id", "") or "")

    def add_favorites(self, kind: str, ids, batch=50):
        """kind in {tracks, albums, artists}. Returns (added, failed, errors)."""
        uid = self.user_collection_id()
        if not uid:
            return 0, len(ids), ["no user_id in session"]
        ids = [str(i) for i in ids if i]
        added = failed = 0
        errors = []
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            body = {"data": [{"type": kind, "id": x} for x in chunk]}
            ok, status, payload = self._post(
                f"/userCollections/{uid}/relationships/{kind}", body,
                params=[("countryCode", self.country())])
            if ok or status == 409:  # 409 = already in collection (idempotent re-run)
                added += len(chunk)
            else:
                failed += len(chunk)
                if len(errors) < 5:
                    errors.append(f"{status}: {str(payload)[:150]}")
        return added, failed, errors

    def create_playlist(self, name: str, description: str = "", access="PUBLIC"):
        attrs = {"name": name or "Untitled", "accessType": access}
        if description:
            attrs["description"] = description
        body = {"data": {"type": "playlists", "attributes": attrs}}
        ok, status, payload = self._post("/playlists", body,
                                         params=[("countryCode", self.country())])
        if ok and isinstance(payload, dict):
            data = payload.get("data", {})
            return str(data.get("id")) if data.get("id") else None
        return None

    def add_playlist_items(self, playlist_id: str, track_ids, batch=50):
        """Append track ids in order. Sequential batches preserve ordering. Returns (added, failed)."""
        track_ids = [str(t) for t in track_ids if t]
        added = failed = 0
        for i in range(0, len(track_ids), batch):
            chunk = track_ids[i:i + batch]
            body = {"data": [{"type": "tracks", "id": x} for x in chunk]}
            ok, status, payload = self._post(
                f"/playlists/{playlist_id}/relationships/items", body,
                params=[("countryCode", self.country())])
            if ok:
                added += len(chunk)
            else:
                failed += len(chunk)
        return added, failed

    def _search(self, query: str, relationship: str, country: str, include: str, limit: int):
        """Shared text-search against /searchResults/{query}/relationships/{relationship}.
        Returns the list of included resource dicts of the wanted type."""
        q = urllib.parse.quote(query.strip()[:200], safe="")
        body = self._get(f"/searchResults/{q}/relationships/{relationship}",
                         [("countryCode", country), ("include", include)])
        if not body or not isinstance(body, dict):
            return []
        want = include
        included = {(_i.get("type"), str(_i.get("id"))): _i for _i in body.get("included", [])}
        out = []
        for ref in body.get("data", [])[:limit]:
            rid = str(ref.get("id"))
            res = included.get((want, rid)) or (ref if ref.get("type") == want else None)
            if res:
                out.append(res)
        return out

    def _delete(self, path: str, body=None, params=None, retries: int = 6):
        """DELETE with optional JSON:API body. Returns (ok, status, parsed_or_text)."""
        self._ensure_token()
        url = f"{API_BASE}{path}"
        for attempt in range(retries):
            self.limiter.wait()
            headers = {"Authorization": f"Bearer {self.session['access_token']}",
                       "Accept": JSONAPI_ACCEPT}
            data = None
            if body is not None:
                headers["Content-Type"] = JSONAPI_ACCEPT
                data = json.dumps(body)
            try:
                resp = self._http.request("DELETE", url, headers=headers, params=params,
                                          data=data, timeout=30)
            except requests.exceptions.RequestException:
                if attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 15)); continue
                return False, 0, "network error"
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "0") or 0) or min(2 ** attempt, 30)
                print(f"    429 rate limited — waiting {wait}s"); time.sleep(wait); continue
            if resp.status_code == 401:
                self._refresh(); continue
            if resp.status_code >= 500 and attempt < retries - 1:
                time.sleep(min(2 ** attempt, 15)); continue
            ok = 200 <= resp.status_code < 300
            return ok, resp.status_code, resp.text[:200]
        return False, 0, "exhausted retries"

    def remove_favorites(self, kind: str, ids, batch=50):
        """Remove tracks/albums/artists from the user's collection. Returns (removed, failed)."""
        uid = self.user_collection_id()
        ids = [str(i) for i in ids if i]
        removed = failed = 0
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            body = {"data": [{"type": kind, "id": x} for x in chunk]}
            ok, status, _ = self._delete(
                f"/userCollections/{uid}/relationships/{kind}", body,
                params=[("countryCode", self.country())])
            if ok or status == 404:
                removed += len(chunk)
            else:
                failed += len(chunk)
        return removed, failed

    def delete_playlist(self, playlist_id: str) -> bool:
        ok, status, _ = self._delete(f"/playlists/{playlist_id}",
                                     params=[("countryCode", self.country())])
        return ok or status == 404

    def search_tracks(self, query: str, country=None, limit=10) -> list:
        """Text fallback. Returns a list of {tidal_id, title, isrc, artist_ids}."""
        country = country or self.country()
        results = []
        for res in self._search(query, "tracks", country, "tracks", limit):
            attrs = res.get("attributes", {}) or {}
            rel = res.get("relationships", {}) or {}
            artist_ids = [str(a.get("id")) for a in (rel.get("artists", {}).get("data") or []) if a.get("id")]
            results.append({
                "tidal_id": str(res.get("id")),
                "title": attrs.get("title", ""),
                "isrc": (attrs.get("isrc") or "").upper(),
                "artist_ids": artist_ids,
            })
        return results

    def search_artists(self, query: str, country=None, limit=10) -> list:
        """Returns [{tidal_id, name}]."""
        country = country or self.country()
        out = []
        for res in self._search(query, "artists", country, "artists", limit):
            attrs = res.get("attributes", {}) or {}
            out.append({"tidal_id": str(res.get("id")), "name": attrs.get("name", "")})
        return out

    def search_albums(self, query: str, country=None, limit=10) -> list:
        """Returns [{tidal_id, title, artist_ids}]."""
        country = country or self.country()
        out = []
        for res in self._search(query, "albums", country, "albums", limit):
            attrs = res.get("attributes", {}) or {}
            rel = res.get("relationships", {}) or {}
            artist_ids = [str(a.get("id")) for a in (rel.get("artists", {}).get("data") or []) if a.get("id")]
            out.append({"tidal_id": str(res.get("id")), "title": attrs.get("title", ""),
                        "artist_ids": artist_ids})
        return out


# CLI

def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <WORK_DIR> auth|probe [ISRC]", file=sys.stderr)
        sys.exit(1)
    work_dir = sys.argv[1]
    cmd = sys.argv[2]
    client = TidalOpenAPI(work_dir)

    if cmd == "auth":
        client.authenticate()
    elif cmd == "probe":
        isrc = sys.argv[3] if len(sys.argv) > 3 else None
        if not isrc:
            print("Provide an ISRC to probe.", file=sys.stderr)
            sys.exit(1)
        res = client.tracks_by_isrc([isrc])
        print(json.dumps(res, indent=2))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
