# Spotify → Tidal Migration Skill

Migrate your entire Spotify music library to Tidal using an AI coding assistant (Claude Code, Cline, Cursor, etc.). The AI handles everything — authenticating both services, matching tracks, importing, and generating reports. You just approve each step.

**What gets migrated:** liked tracks, saved albums, followed artists, all playlists (tracks in Spotify order), and a special "Liked Songs" playlist on Tidal with your liked tracks in the exact order they appear on Spotify.

## Prerequisites

- Python 3.8+ with `pip install requests`
- A Spotify account and a Tidal account
- An AI coding assistant that supports skills/custom instructions (Claude Code, Cline, Cursor, etc.)

---

## Setup

### Step 1 — Create a Spotify Developer App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in
2. Click **Create app**
3. Set Redirect URI to: `http://127.0.0.1:3030/callback`
4. Note your **Client ID** and **Client Secret**
5. Under **User Management**, add your Spotify account email address (required while in development mode)

### Step 2 — Create a Tidal Developer App

1. Go to [developer.tidal.com/dashboard/apps](https://developer.tidal.com/dashboard/apps) and log in
2. Click **Create app**
3. Set **Access tier** to: `THIRD_PARTY`
4. Set Redirect URI to: `http://localhost:3030/callback`
5. Enable these scopes: `user.read`, `collection.read`, `collection.write`, `playlists.read`, `playlists.write`, `search.read`
6. Note your **Client ID** and **Client Secret**

### Step 3 — Create a Working Directory

```bash
mkdir spotify-tidal-working-directory
```

Create a file named `spotify-to-tidal.env` inside it:

```
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
TIDAL_CLIENT_ID=your_tidal_client_id
TIDAL_CLIENT_SECRET=your_tidal_client_secret
```

### Step 4 — Load the Skill and Run

Load this skill into your AI tool (point it at this `SKILL.md` file or the skill directory), then tell it:

> "Migrate my music from Spotify to Tidal. My working directory is `./spotify-tidal-working-directory`"

The AI will walk through each phase, pause for your approval at key checkpoints, and handle all the auth, matching, and importing automatically.

---

## What Happens (Phases)

| Phase | What the AI does | Your involvement |
|---|---|---|
| **1. Spotify Export** | Authenticates to Spotify, fetches your full library, saves JSON | Open a browser auth page once |
| **2. Tidal Auth** | PKCE login to the official Tidal v2 API | Open a browser auth page once |
| **3. Analysis** | Matches every track by exact ISRC against Tidal's catalog (read-only) | Wait; AI shows you match stats |
| **4. Import** | Likes tracks, saves albums, follows artists, creates playlists, creates "Liked Songs" playlist | Approve before it starts |
| **5. Verify** | Reads your Tidal account back and checks everything landed | Review the health report |
| **6. Reports** | Generates HTML reports for migration, verification, and missing tracks | Open the HTML files in a browser |

The import is **append-only and idempotent** — re-running is safe and skips items already in Tidal.

---

## Running Individual Phases

You don't have to run everything at once. Tell the AI what you want:

| Say this | What runs |
|---|---|
| "Export my Spotify library" | Phase 1 only |
| "Analyze the Tidal import" | Phase 3 only (requires Spotify export) |
| "Import to Tidal" | Phase 4 only (requires analysis) |
| "Verify my Tidal import" | Phase 5 only |
| "Generate migration report" | HTML report from existing result files |
| "What tracks didn't transfer?" | Missing tracks HTML report |

---

## Output Files

All files are written to your working directory:

| File | What it contains |
|---|---|
| `spotify-export.json` | Your full Spotify library |
| `tidal-match-cache.json` | ISRC → Tidal ID match cache (resumable) |
| `tidal-analysis.json` | Human-readable match summary |
| `tidal-import-result.json` | Import results |
| `tidal-verification-result.json` | Verification read-back results |
| `migration-report.html` | Overview: what was imported |
| `verification-report.html` | Health check: what's actually on Tidal |
| `tidal-missing-tracks-report.html` | Tracks not found in Tidal's catalog |
| `spotify-tokens.json` | Spotify OAuth tokens (auto-managed) |
| `tidal-openapi-session.json` | Tidal PKCE session (auto-managed) |

---

## Tips

- **Interrupted run?** Re-run the same command — the match cache resumes from where it stopped, no repeated lookups.
- **Already have some tracks on Tidal?** The import is append-only; existing items won't be duplicated.
- **Missing tracks?** Open `tidal-missing-tracks-report.html` — these are tracks unavailable in Tidal's catalog (or region-locked), not import errors.
- **"Liked Songs" playlist** appears as a regular UNLISTED playlist on Tidal alongside your other playlists, with your liked songs in Spotify order.

---

## License

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.

Copyright (c) 2026 aalzubidy

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
