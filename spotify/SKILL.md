# Spotify Export Phase

> **⚠️ CRITICAL: Spotify is READ-ONLY. This phase only READS data — it never writes, modifies, or deletes anything on Spotify. Do not attempt to create playlists, add tracks, follow artists, or make any changes to the Spotify account. The Spotify app used here has zero write scopes.**

Exports the user's entire Spotify library to a structured JSON file.

## Prerequisites

- Python 3.8+
- The `spotify-to-tidal.env` file with valid `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`
- Internet connection and a web browser

## Step 1 — Load Credentials

Set the working directory (the directory containing `spotify-to-tidal.env`):

```bash
WORK_DIR="/path/to/spotify-tidal-working-directory"
source "$WORK_DIR/spotify-to-tidal.env"
```

Verify the variables are set:
```bash
echo "Client ID: ${SPOTIFY_CLIENT_ID:0:8}..."
```

## Step 2 — Start Auth Server

Run the authorization server:

```bash
cd .agents/skills/spotify-to-tidal/spotify
mkdir -p "$WORK_DIR"
PYTHONDONTWRITEBYTECODE=1 python3 helpers/auth-server.py "$SPOTIFY_CLIENT_ID" "$SPOTIFY_CLIENT_SECRET" "$WORK_DIR"
```

This starts an HTTP server on `http://127.0.0.1:3030`.

It will print a URL. Open that URL in your browser, log in with Spotify,
and approve the requested scopes. You'll be redirected back to `127.0.0.1`,
the server captures the authorization code, exchanges it for tokens,
and saves them to `$WORK_DIR/spotify-tokens.json`.

The server shuts down after successful auth.

Scopes requested:
- `user-library-read` — liked tracks, saved albums/episodes/shows/audiobooks
- `playlist-read-private` — private playlists
- `playlist-read-collaborative` — collaborative playlists
- `user-follow-read` — followed artists
- `user-top-read` — top artists and tracks
- `user-read-recently-played` — recently played

## Step 3 — Fetch All Data

Once tokens are saved, run the fetcher:

```bash
cd .agents/skills/spotify-to-tidal/spotify
WORK_DIR="/path/to/spotify-tidal-working-directory"
PYTHONDONTWRITEBYTECODE=1 python3 helpers/fetch-all.py "$WORK_DIR/spotify-tokens.json" "$WORK_DIR/spotify-export.json"
```

This pulls all data using the Spotify Web API:

| Endpoint | Section |
|---|---|
| `GET /me/tracks` | `liked_tracks` |
| `GET /me/albums` | `saved_albums` |
| `GET /me/episodes` | `saved_episodes` |
| `GET /me/shows` | `saved_shows` |
| `GET /me/audiobooks` | `saved_audiobooks` |
| `GET /me/playlists` + per-playlist `GET /playlists/{id}/tracks` | `playlists` |
| `GET /me/following?type=artist` | `followed_artists` |
| `GET /me/top/artists` (long_term) | `top_artists` |
| `GET /me/top/tracks` (long_term) | `top_tracks` |
| `GET /me/player/recently-played` | `recently_played` |

All endpoints are paginated — the fetcher follows `next` links automatically.
Rate limiting is handled with `Retry-After` header support.

## Step 4 — Verify Output

```bash
WORK_DIR="/path/to/spotify-tidal-working-directory"
python3 -c "
import json
with open('$WORK_DIR/spotify-export.json') as f:
    d = json.load(f)
print(f'Tracks: {len(d[\"liked_tracks\"])}')
print(f'Albums: {len(d[\"saved_albums\"])}')
print(f'Playlists: {len(d[\"playlists\"])}')
print(f'Artists: {len(d[\"followed_artists\"])}')
"
```

## Step 5 — Generate Report (Optional)

See the master `SKILL.md` report section.

```bash
cd .agents/skills/spotify-to-tidal
WORK_DIR="/path/to/spotify-tidal-working-directory"
PYTHONDONTWRITEBYTECODE=1 python3 reports/generate.py --type export \
  --input "$WORK_DIR/spotify-export.json" \
  --output "$WORK_DIR/spotify-report.html"
```
