# Spotify to Tidal Migration — AI Skill for Claude Code, Cursor & Cline

Migrate your entire Spotify music library to Tidal using an AI coding assistant (Claude Code, Claude Desktop, Cursor, VS Code/Cursor Cline, OpenCode, Codex CLI, Pi). The AI handles everything — authenticating both services, matching tracks by **ISRC**, importing, keeping your playlists in order, and generating reports for failed imports.

**What gets migrated:** liked tracks, saved albums, followed artists, all playlists (tracks in Spotify order), and a special "Liked Songs" playlist on Tidal with your liked tracks in the exact order they appear on Spotify.

---

## Quick Start (no tech experience needed)

You don't need to know how to code. You'll copy-paste a few commands and two sets of "keys" (like passwords apps use to talk to each other), and an AI assistant does the rest. This guide uses **Claude Desktop** [claude.ai/download](https://claude.ai/download):

1. **Install this skill.** Open a terminal (Mac/Linux: search "Terminal" in Spotlight; Windows: search "Terminal") and paste:
   ```bash
   curl -sSf https://raw.githubusercontent.com/aalzubidy/spotify-to-tidal/master/install.sh | bash
   ```
   This copies the migration instructions into Claude Desktop automatically.

2. **Get your Spotify keys.** Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard), log in with your normal Spotify account, click **Create app**, give it a name, set the Redirect URI to `http://127.0.0.1:3030/callback`, select web api under which SDK to use. Once created, you'll see a **Client ID** and **Client Secret** — keep this page open, you'll need to copy them in step 4. Also add your own Spotify email under **User Management** on that same app page.

3. **Get your Tidal keys.** Go to [developer.tidal.com/dashboard/](https://developer.tidal.com/dashboard/), log in with your Tidal account, click **Create app**, give it a name, create it, then click on settings and set the Redirect URI to `http://localhost:3030/callback`. On the scopes section, select all available permissions.Click save. Copy the **Client ID** and **Client Secret** it gives you.

4. **Make a folder for your keys.** Create a new folder anywhere (e.g. on your Desktop) called `spotify-tidal-working-directory`. Inside it, create a plain text file named `spotify-to-tidal.env` with this content, filling in the four values you copied above:
   ```
   SPOTIFY_CLIENT_ID=paste_your_spotify_client_id
   SPOTIFY_CLIENT_SECRET=paste_your_spotify_client_secret
   TIDAL_CLIENT_ID=paste_your_tidal_client_id
   TIDAL_CLIENT_SECRET=paste_your_tidal_client_secret
   ```

5. **Ask Claude to do the migration.** Open Claude Desktop and type:
   > "Migrate my music from Spotify to Tidal. My working directory is `./spotify-tidal-working-directory` (full path: paste the actual folder path here)"

   Claude will open your browser twice (once to log into Spotify, once for Tidal), then handle matching and importing everything for you — pausing to ask before it changes anything on your Tidal account. When it's done, it'll show you an HTML report you can open in your browser with the results.

That's it. If you get stuck on any step, the sections below have more detail, or ask your AI assistant directly — it can usually walk you through it.

---

## Why this vs. other Spotify → Tidal tools

- **Runs locally & private** — unlike web services (TuneMyMusic, FreeYourMusic), nothing but your own machine and the official APIs see your library.
- **ISRC-exact matching** — tracks are matched by exact ISRC against Tidal's catalog, not fuzzy title/artist guessing.
- **Full library, in order** — playlists, liked songs (in original Spotify order), saved albums, and followed artists — not just playlists.
- **Absolutely Free** - You don't pay anything, clone it, add it to your agent and it's free to use - no limit on songs.
- **Personally Tested** - I personally tested it with my own library of 10k+ songs and playlists and getting about 93% coverage due to some songs not available on Tidal.

---

## Full Setup & Reference

The Quick Start above is enough for most people. This section has the full detail — other AI tools besides Claude Desktop, all install flags, and the exact prerequisites.

### Install

```bash
curl -sSf https://raw.githubusercontent.com/aalzubidy/spotify-to-tidal/master/install.sh | bash
```

Or clone and run locally:

```bash
git clone https://github.com/aalzubidy/spotify-to-tidal.git
cd spotify-to-tidal
./install.sh             # interactive — picks which tools to install
./install.sh --all       # install to every detected AI tool
./install.sh --claude    # Claude Code / Claude Desktop only
./install.sh --opencode  # OpenCode only
./install.sh --cursor    # Cursor (native skills) only
./install.sh --codex     # Codex CLI only
./install.sh --cline     # VS Code / Cursor Cline extension only
./install.sh --pi        # Pi coding agent only
```

The script auto-detects which AI coding assistants you have installed and installs the skill into their skills directory. Supported tools:

- Claude Code / Claude Desktop (`~/.claude/skills`)
- OpenCode (`~/.config/opencode/skills`)
- Cursor (`~/.cursor/skills`)
- Codex CLI (`~/.agents/skills`)
- VS Code / Cursor Cline extension (`~/.cline/skills`)
- Pi coding agent (`~/.pi/agent/skills`)

After installation, follow the setup steps below and tell your AI tool: *"Migrate my music from Spotify to Tidal"*

### Prerequisites

- Python 3.8+ with `pip install requests`
- A Spotify account and a Tidal account
- An AI coding assistant that supports skills/custom instructions (Claude Code, Claude Desktop, Cursor, VS Code/Cursor Cline, OpenCode, Codex CLI, Pi)

### Setup

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

[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-blue.svg)](LICENSE)

This project is licensed under the Mozilla Public License 2.0 — see the [LICENSE](LICENSE) file for details.
Copyright (c) 2026 aalzubidy.
