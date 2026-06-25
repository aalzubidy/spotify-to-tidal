# Tidal Import Phase

Imports a Spotify export into Tidal using the **official TIDAL v2 API**
(`openapi.tidal.com/v2`) with Authorization-Code + PKCE auth.

Matching is **exact**: every track is resolved by its ISRC via
`GET /tracks?filter[isrc]=...` (batched), not by fuzzy text search. Albums match
by UPC barcode, artists by name. All matches are written to a **resumable cache**
(`tidal-match-cache.json`) so a killed or rate-limited run picks up where it left
off instead of starting over.

> **⚠️ All writes go to Tidal only. Never write, modify, or delete anything on Spotify.**

## Why the official API

Tidal's *internal* `api.tidal.com/v1` API has no ISRC filter, which used to force
fragile "search album → fuzzy match → guess track" logic (slow, error-prone, and
aggressively rate-limited). The official v2 API supports exact ISRC/barcode lookup
in batches, so ~6.5k unique tracks resolve in a few hundred requests. The internal
v1 path and device-code flow have been **retired**.

## Prerequisites

- Python 3.8+ and `requests` (`pip install requests`)
- A TIDAL developer app (https://developer.tidal.com) with:
  - `TIDAL_CLIENT_ID` / `TIDAL_CLIENT_SECRET` in the working-dir `spotify-to-tidal.env`
  - a redirect URI of `http://localhost:3030/callback` registered on the app
  - scopes granting collection + playlists read/write
- A completed `spotify-export.json` from the Spotify export phase

## Step 1 — Authenticate (one-time, browser)

```bash
WORK_DIR="/path/to/spotify-tidal-working-directory"
python3 .agents/skills/spotify-to-tidal/tidal/helpers/tidal_openapi.py "$WORK_DIR" auth
```

Opens a TIDAL login URL, captures the redirect on `localhost:3030`, and saves
`tidal-openapi-session.json` (access + refresh tokens, user id, country). Tokens
auto-refresh; no need to re-auth unless the refresh token is revoked.

Sanity-check a single lookup any time:
```bash
python3 .agents/skills/spotify-to-tidal/tidal/helpers/tidal_openapi.py "$WORK_DIR" probe USRC11700001
```

## Step 2 — Analyze (match) — read-only

Resolves every ISRC to a Tidal track and writes `tidal-match-cache.json`.

```bash
python3 .agents/skills/spotify-to-tidal/tidal/helpers/analyze-import.py \
  "$WORK_DIR/spotify-export.json" \
  "$WORK_DIR" \
  "$WORK_DIR/tidal-analysis.json"
```

- ISRC-exact matching first (batched, `--batch N`, default 20 per request).
- Capped text-search fallback for ISRC misses (`--fallback-cap N`, or `--no-fallback`).
- Albums by UPC barcode (needs UPC in the export) then fuzzy fallback; artists by name.
- `--limit N` matches only the first N ISRCs — use for a quick test slice.
- **Resumable:** re-running skips everything already in `tidal-match-cache.json`.

`tidal-analysis.json` is a human-readable summary (match rates, per-playlist).
Present it to the user before importing.

## Step 3 — Import (write)

Reads the match cache and writes to Tidal. **Append-only and idempotent** —
re-running skips items already in the collection (HTTP 409 treated as success).

```bash
python3 .agents/skills/spotify-to-tidal/tidal/helpers/import-all.py \
  "$WORK_DIR/spotify-export.json" \
  "$WORK_DIR" \
  "$WORK_DIR/tidal-import-result.json"
```

Selectively skip categories with `--no-liked`, `--no-albums`, `--no-artists`,
`--no-playlists`, `--no-liked-playlist`.

What it does (all batched 50/request):
1. **Like tracks** → `POST /userCollections/{userId}/relationships/tracks`
2. **Save albums** → `POST /userCollections/{userId}/relationships/albums`
3. **Follow artists** → `POST /userCollections/{userId}/relationships/artists`
4. **Create playlists** → `POST /playlists`
5. **Add playlist tracks in Spotify order** → `POST /playlists/{id}/relationships/items`
   (sequential batches append in order, preserving the original sequence)
6. **Create "Liked Songs" playlist** → liked tracks in Spotify order as a browsable UNLISTED
   playlist (in addition to the liked-track favorites). Skip with `--no-liked-playlist`.

| Spotify data | Tidal action | Match method |
|---|---|---|
| Liked tracks | Favorite tracks | ISRC exact (+ capped search fallback) |
| Saved albums | Saved albums | UPC barcode / fuzzy; plus albums of matched tracks |
| Followed artists | Followed artists | Name search; plus artists of matched tracks |
| Playlists | Created, tracks in order | ISRC exact |
| Liked Songs playlist | Created UNLISTED, liked tracks in order | ISRC exact |

## Step 4 — Clean library (optional, destructive)

Empties categories before a fresh import. Dry-run by default.

```bash
# Dry run
python3 .agents/skills/spotify-to-tidal/tidal/helpers/clean-library.py \
  "$WORK_DIR" --categories tracks,albums,artists,playlists

# Actually delete (typed confirmation required)
python3 .agents/skills/spotify-to-tidal/tidal/helpers/clean-library.py \
  "$WORK_DIR" --categories tracks,albums,artists,playlists --confirm
```

## Step 5 — Verify

Reads back the actual Tidal account state and cross-references the match cache.

```bash
python3 .agents/skills/spotify-to-tidal/tidal/helpers/verify-import.py \
  "$WORK_DIR/spotify-export.json" \
  "$WORK_DIR" \
  "$WORK_DIR/tidal-import-result.json" \
  "$WORK_DIR/tidal-verification-result.json"
```

Reports liked-track presence, per-playlist track presence, and playlists found.

## Step 6 — Report

```bash
PYTHONDONTWRITEBYTECODE=1 python3 reports/generate.py --type import \
  --input "$WORK_DIR/tidal-import-result.json" \
  --output "$WORK_DIR/tidal-report.html"
```

## Files (working directory)

| File | Purpose |
|---|---|
| `spotify-to-tidal.env` | `TIDAL_CLIENT_ID/SECRET` (+ Spotify creds) |
| `tidal-openapi-session.json` | Official-API PKCE session (auto-refresh) |
| `tidal-match-cache.json` | **Resumable** ISRC/album/artist → Tidal ID cache |
| `tidal-analysis.json` | Human-readable match summary |
| `tidal-import-result.json` | Import results |
| `tidal-verification-result.json` | Read-back verification |

## Architecture

All scripts share `tidal/helpers/tidal_openapi.py` (`TidalOpenAPI`):

- **API base:** `openapi.tidal.com/v2` (official JSON:API)
- **Auth:** Authorization Code + PKCE; tokens in `tidal-openapi-session.json`
- **Rate limiting:** steady pacing (`TIDAL_OPENAPI_MIN_INTERVAL`, default ~8 req/s)
  plus exact `Retry-After` honoring on 429 — no burst-then-backoff
- **Matching:** `tracks_by_isrc`, `albums_by_barcode`, `search_tracks/artists/albums`
- **Writes:** `add_favorites`, `create_playlist`, `add_playlist_items`
- **Reads:** `get_collection_ids`, `get_user_playlists`, `get_playlist_item_ids`

### Tuning

- `--batch N` on analyze: ISRCs per ISRC request (default 20).
- `TIDAL_OPENAPI_MIN_INTERVAL=0.2` in the `.env`: slow down if you still hit 429s.
- `--fallback-cap N` / `--no-fallback`: control text-search fallback volume.
