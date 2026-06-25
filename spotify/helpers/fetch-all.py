#!/usr/bin/env python3
"""
Spotify Library Fetcher

Reads all user library data via the Spotify Web API using the stored
OAuth2 tokens. Handles pagination and rate limiting automatically.

Usage:
    python3 fetch-all.py <TOKENS_FILE> <OUTPUT_FILE>
"""

import sys
import json
import time
import base64
import urllib.request
import urllib.parse
import urllib.error
import os


SPOTIFY_API = "https://api.spotify.com/v1"


def load_tokens(tokens_path):
    """Load and validate Spotify tokens."""
    with open(tokens_path, "r") as f:
        tokens = json.load(f)

    if "access_token" not in tokens:
        raise ValueError("No access_token in tokens file")

    # If expired, try refreshing
    if tokens.get("expires_in") and tokens.get("obtained_at"):
        expires_at = tokens["obtained_at"] + tokens["expires_in"] - 60
        if time.time() > expires_at:
            if "refresh_token" in tokens:
                tokens = refresh_tokens(tokens, tokens_path)
            else:
                raise ValueError("Token expired and no refresh_token available")

    return tokens


def refresh_tokens(tokens, tokens_path, client_id=None, client_secret=None):
    """Refresh an expired access token. Requires client_id/client_secret
    in tokens or passed as arguments."""
    cid = client_id or tokens.get("client_id")
    secret = client_secret or tokens.get("client_secret")
    refresh = tokens.get("refresh_token")

    if not cid or not secret or not refresh:
        raise ValueError("Missing client_id, client_secret, or refresh_token for refresh")

    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }).encode()

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    # Some token endpoints require basic auth for refresh
    auth_header = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth_header}")

    try:
        with urllib.request.urlopen(req) as resp:
            new_tokens = json.loads(resp.read().decode())
    except urllib.error.HTTPError:
        # Try without basic auth
        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req) as resp:
            new_tokens = json.loads(resp.read().decode())

    tokens["access_token"] = new_tokens["access_token"]
    tokens["obtained_at"] = int(time.time())
    if "refresh_token" in new_tokens:
        tokens["refresh_token"] = new_tokens["refresh_token"]
    if "expires_in" in new_tokens:
        tokens["expires_in"] = new_tokens["expires_in"]

    with open(tokens_path, "w") as f:
        json.dump(tokens, f, indent=2)

    return tokens


def api_get(url, token, retries=3):
    """Make an authenticated GET request to the Spotify API with retry."""
    for attempt in range(retries):
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Rate limited - wait for Retry-After header
                retry_after = int(e.headers.get("Retry-After", 5))
                print(f"  Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            elif e.code == 401 and attempt < retries - 1:
                print(f"  Token expired, please re-authenticate")
                raise
            else:
                print(f"  HTTP {e.code}: {e.reason} for {url}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        except urllib.error.URLError as e:
            print(f"  Network error: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise

    return None


def fetch_paginated(url, token, limit=50, max_items=None):
    """Fetch all pages from a paginated Spotify endpoint."""
    items = []
    page_url = f"{url}?limit={limit}"

    while page_url and (max_items is None or len(items) < max_items):
        print(f"  Fetching: {urllib.parse.urlparse(page_url).path}...")
        data = api_get(page_url, token)

        if data is None:
            break

        batch = data.get("items", [])
        if batch:
            items.extend(batch)
            print(f"    Got {len(batch)} items (total: {len(items)})")
        else:
            print(f"    No items in this batch")

        page_url = data.get("next")

    return items


def extract_track(track_obj):
    """Extract relevant fields from a Spotify track object."""
    if track_obj is None:
        return None

    # Tracks in /me/tracks come wrapped in an 'added_at' object
    track = track_obj.get("track", track_obj)

    artists = [
        {"name": a.get("name", ""), "spotify_id": a.get("id", "")}
        for a in track.get("artists", [])
    ]

    album = track.get("album", {})

    result = {
        "spotify_id": track.get("id"),
        "name": track.get("name"),
        "artists": artists,
        "album": {
            "name": album.get("name"),
            "spotify_id": album.get("id"),
            "release_date": album.get("release_date"),
            "album_type": album.get("album_type"),
        },
        "duration_ms": track.get("duration_ms"),
        "isrc": track.get("external_ids", {}).get("isrc", ""),
        "popularity": track.get("popularity"),
        "explicit": track.get("explicit"),
        "preview_url": track.get("preview_url"),
    }

    # Include added_at for liked tracks
    if "added_at" in track_obj:
        result["added_at"] = track_obj["added_at"]

    return result


def fetch_me_info(token):
    """Get the current user's profile info."""
    print("\n[User Info]")
    data = api_get(f"{SPOTIFY_API}/me", token)
    if data:
        print(f"  User: {data.get('display_name')} ({data.get('id')})")
        return {
            "spotify_user_id": data.get("id"),
            "spotify_display_name": data.get("display_name"),
            "spotify_email": data.get("email"),
            "spotify_country": data.get("country"),
        }
    return {}


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <TOKENS_FILE> <OUTPUT_FILE>", file=sys.stderr)
        sys.exit(1)

    tokens_path = sys.argv[1]
    output_path = sys.argv[2]

    print("=" * 60)
    print("  Spotify Library Fetcher")
    print("=" * 60)

    tokens = load_tokens(tokens_path)
    token = tokens["access_token"]

    # Get user info
    user_info = fetch_me_info(token)

    export = {
        "export_info": {
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **user_info,
        },
        "liked_tracks": [],
        "saved_albums": [],
        "saved_episodes": [],
        "saved_shows": [],
        "saved_audiobooks": [],
        "playlists": [],
        "followed_artists": [],
        "top_artists": [],
        "top_tracks": [],
        "recently_played": [],
    }

    # --- Liked Tracks ---
    print("\n[Liked Tracks]")
    liked = fetch_paginated(f"{SPOTIFY_API}/me/tracks", token, limit=50)
    export["liked_tracks"] = []
    for item in liked:
        track_data = extract_track(item)
        if track_data:
            export["liked_tracks"].append(track_data)

    # --- Saved Albums ---
    print("\n[Saved Albums]")
    albums = fetch_paginated(f"{SPOTIFY_API}/me/albums", token, limit=50)
    export["saved_albums"] = [
        {
            "spotify_id": a.get("album", a).get("id"),
            "name": a.get("album", a).get("name"),
            "artists": [
                {"name": art.get("name"), "spotify_id": art.get("id")}
                for art in a.get("album", a).get("artists", [])
            ],
            "release_date": a.get("album", a).get("release_date"),
            "total_tracks": a.get("album", a).get("total_tracks"),
            "album_type": a.get("album", a).get("album_type"),
            # UPC barcode enables exact album matching on Tidal (filter[barcodeId])
            "upc": a.get("album", a).get("external_ids", {}).get("upc", ""),
            "added_at": a.get("added_at"),
        }
        for a in albums
        if a.get("album")
    ]

    # --- Saved Episodes ---
    print("\n[Saved Episodes]")
    episodes = fetch_paginated(f"{SPOTIFY_API}/me/episodes", token, limit=50)
    export["saved_episodes"] = [
        {
            "spotify_id": e.get("episode", e).get("id"),
            "name": e.get("episode", e).get("name"),
            "show": e.get("episode", e).get("show", {}).get("name"),
            "duration_ms": e.get("episode", e).get("duration_ms"),
            "release_date": e.get("episode", e).get("release_date"),
            "added_at": e.get("added_at"),
        }
        for e in episodes
        if e.get("episode")
    ]

    # --- Saved Shows ---
    print("\n[Saved Shows]")
    shows = fetch_paginated(f"{SPOTIFY_API}/me/shows", token, limit=50)
    export["saved_shows"] = [
        {
            "spotify_id": s.get("show", s).get("id"),
            "name": s.get("show", s).get("name"),
            "publisher": s.get("show", s).get("publisher"),
            "total_episodes": s.get("show", s).get("total_episodes"),
            "added_at": s.get("added_at"),
        }
        for s in shows
        if s.get("show")
    ]

    # --- Saved Audiobooks ---
    print("\n[Saved Audiobooks]")
    audiobooks = fetch_paginated(f"{SPOTIFY_API}/me/audiobooks", token, limit=50)
    export["saved_audiobooks"] = [
        {
            "spotify_id": a.get("id"),
            "name": a.get("name"),
            "authors": [{"name": auth.get("name")} for auth in a.get("authors", [])],
            "total_chapters": a.get("total_chapters"),
        }
        for a in audiobooks
    ]

    # --- Playlists ---
    print("\n[Playlists]")
    playlists = fetch_paginated(f"{SPOTIFY_API}/me/playlists", token, limit=50)
    export["playlists"] = []

    for i, pl in enumerate(playlists):
        pl_id = pl.get("id")
        pl_name = pl.get("name", "Unknown")
        print(f"\n  [{i+1}/{len(playlists)}] Playlist: {pl_name}")

        pl_data = {
            "spotify_id": pl_id,
            "name": pl_name,
            "description": pl.get("description", ""),
            "public": pl.get("public"),
            "track_count": pl.get("tracks", {}).get("total", 0),
            "owner": pl.get("owner", {}).get("display_name"),
            "tracks": [],
        }

        # Fetch all tracks in this playlist
        try:
            pl_tracks = fetch_paginated(
                f"{SPOTIFY_API}/playlists/{pl_id}/tracks", token, limit=100
            )
            for item in pl_tracks:
                track_data = extract_track(item)
                if track_data:
                    pl_data["tracks"].append(track_data)
        except Exception as e:
            print(f"    ⚠️ Could not fetch tracks: {e}")

        export["playlists"].append(pl_data)

    # --- Followed Artists ---
    print("\n[Followed Artists]")
    after = None
    followed = []

    while True:
        url = f"{SPOTIFY_API}/me/following?type=artist&limit=50"
        if after:
            url += f"&after={after}"

        print(f"  Fetching followed artists...")
        data = api_get(url, token)

        if not data:
            break

        artists_batch = data.get("artists", {}).get("items", [])
        if not artists_batch:
            break

        for a in artists_batch:
            followed.append({
                "spotify_id": a.get("id"),
                "name": a.get("name"),
                "genres": a.get("genres", []),
                "popularity": a.get("popularity"),
                "followers": a.get("followers", {}).get("total"),
            })

        print(f"    Got {len(artists_batch)} artists (total: {len(followed)})")
        after = data.get("artists", {}).get("cursors", {}).get("after")
        if not after:
            break

    export["followed_artists"] = followed

    # --- Top Artists ---
    print("\n[Top Artists - Long Term]")
    top_artists = fetch_paginated(
        f"{SPOTIFY_API}/me/top/artists", token,
        limit=50, max_items=50,
    )
    # Add time_range parameter
    top_artists_full = api_get(
        f"{SPOTIFY_API}/me/top/artists?limit=50&time_range=long_term", token
    )
    if top_artists_full:
        top_artists = top_artists_full.get("items", [])

    export["top_artists"] = [
        {
            "spotify_id": a.get("id"),
            "name": a.get("name"),
            "genres": a.get("genres", []),
            "popularity": a.get("popularity"),
        }
        for a in (top_artists or [])
    ]

    # --- Top Tracks ---
    print("\n[Top Tracks - Long Term]")
    top_tracks_data = api_get(
        f"{SPOTIFY_API}/me/top/tracks?limit=50&time_range=long_term", token
    )
    if top_tracks_data:
        export["top_tracks"] = [
            extract_track({"track": t}) for t in top_tracks_data.get("items", [])
        ]

    # --- Recently Played ---
    print("\n[Recently Played]")
    recent = api_get(f"{SPOTIFY_API}/me/player/recently-played?limit=50", token)
    if recent:
        export["recently_played"] = [
            {
                **extract_track({"track": item.get("track")}),
                "played_at": item.get("played_at"),
            }
            for item in recent.get("items", [])
            if item.get("track")
        ]

    # --- Summary ---
    export["export_info"]["total_tracks"] = len(export["liked_tracks"])
    export["export_info"]["total_albums"] = len(export["saved_albums"])
    export["export_info"]["total_episodes"] = len(export["saved_episodes"])
    export["export_info"]["total_shows"] = len(export["saved_shows"])
    export["export_info"]["total_audiobooks"] = len(export["saved_audiobooks"])
    export["export_info"]["total_playlists"] = len(export["playlists"])
    export["export_info"]["total_followed_artists"] = len(export["followed_artists"])

    # --- Save ---
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(export, f, indent=2)

    print("\n" + "=" * 60)
    print("  Export Complete!")
    print("=" * 60)
    print(f"  Liked Tracks:      {export['export_info']['total_tracks']}")
    print(f"  Saved Albums:      {export['export_info']['total_albums']}")
    print(f"  Saved Episodes:    {export['export_info']['total_episodes']}")
    print(f"  Saved Shows:       {export['export_info']['total_shows']}")
    print(f"  Saved Audiobooks:  {export['export_info']['total_audiobooks']}")
    print(f"  Playlists:         {export['export_info']['total_playlists']}")
    print(f"  Followed Artists:  {export['export_info']['total_followed_artists']}")
    print(f"  Top Artists:       {len(export['top_artists'])}")
    print(f"  Top Tracks:        {len(export['top_tracks'])}")
    print(f"  Recently Played:   {len(export['recently_played'])}")
    print(f"\n  Saved to: {output_path}")


if __name__ == "__main__":
    main()