#!/usr/bin/env python3
"""
Tidal Import Verifier — official v2 API

Reads back the user's actual Tidal account state and cross-references it against
what we expected to import (the match cache + import result). Reports per-category
health: how many expected IDs are actually present, and per-playlist track counts.

Usage:
    python3 verify-import.py <SPOTIFY_EXPORT_JSON> <WORK_DIR> <IMPORT_RESULT_JSON> <OUTPUT_JSON>
"""

import sys
sys.dont_write_bytecode = True
import json
import os
import time

from tidal_openapi import TidalOpenAPI

CACHE_FILENAME = "tidal-match-cache.json"


def isrc_of(t):
    return (t.get("isrc") or "").upper().strip()


def pct(a, b):
    return round(100 * a / b, 1) if b else 100.0


def main():
    if len(sys.argv) < 5:
        print(f"Usage: {sys.argv[0]} <SPOTIFY_EXPORT_JSON> <WORK_DIR> <IMPORT_RESULT_JSON> <OUTPUT_JSON>",
              file=sys.stderr)
        sys.exit(1)
    spotify_path, work_dir, import_result_path, output_path = sys.argv[1:5]

    print("=" * 60)
    print("  Tidal Import Verifier — official v2 API")
    print("=" * 60)

    sp = json.load(open(spotify_path))
    cache = json.load(open(os.path.join(work_dir, CACHE_FILENAME)))
    import_result = json.load(open(import_result_path)) if os.path.exists(import_result_path) else {}
    track_map = cache.get("tracks", {})

    client = TidalOpenAPI(work_dir)
    if not client.is_authenticated():
        print("\n  ERROR: not authenticated. Run tidal_openapi.py <WORK_DIR> auth", file=sys.stderr)
        sys.exit(2)

    print("\n[Reading Tidal account state]")
    actual_tracks = client.get_collection_ids("tracks")
    print(f"  favorite tracks on Tidal: {len(actual_tracks)}")
    actual_albums = client.get_collection_ids("albums")
    print(f"  saved albums on Tidal:    {len(actual_albums)}")
    actual_artists = client.get_collection_ids("artists")
    print(f"  followed artists on Tidal:{len(actual_artists)}")
    tidal_playlists = client.get_user_playlists()
    pl_by_name = {}
    for p in tidal_playlists:
        pl_by_name.setdefault(p["name"].strip().lower(), p)
    print(f"  playlists on Tidal:       {len(tidal_playlists)}")

    # Expected liked-track Tidal IDs
    expected_liked = set()
    for t in sp.get("liked_tracks", []):
        m = track_map.get(isrc_of(t))
        if m:
            expected_liked.add(str(m["tidal_id"]))
    liked_present = len(expected_liked & actual_tracks)

    verification = {
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api": "official_v2",
        "tidal_state": {
            "favorite_tracks": len(actual_tracks),
            "saved_albums": len(actual_albums),
            "followed_artists": len(actual_artists),
            "playlists": len(tidal_playlists),
        },
        "liked_tracks": {
            "expected": len(expected_liked),
            "present": liked_present,
            "missing": len(expected_liked) - liked_present,
            "health": f"{pct(liked_present, len(expected_liked))}%",
        },
        "playlists": [],
    }

    # Per-playlist verification
    print("\n[Verifying playlists]")
    for pl in sp.get("playlists", []):
        name = pl.get("name", "Untitled")
        expected_ids = [str(track_map[isrc_of(t)]["tidal_id"])
                        for t in pl.get("tracks", []) if isrc_of(t) in track_map]
        tp = pl_by_name.get(name.strip().lower())
        entry = {"name": name, "expected_tracks": len(expected_ids),
                 "found_on_tidal": bool(tp)}
        if tp:
            actual_ids = client.get_playlist_item_ids(tp["id"])
            present = len(set(expected_ids) & set(actual_ids))
            entry.update({"tidal_track_count": len(actual_ids), "present": present,
                          "health": f"{pct(present, len(expected_ids))}%"})
            icon = "OK" if present >= len(expected_ids) else "!!"
            print(f"  [{icon}] {name}: {present}/{len(expected_ids)} present "
                  f"(tidal has {len(actual_ids)})")
        else:
            entry.update({"tidal_track_count": 0, "present": 0, "health": "0.0%"})
            print(f"  [??] {name}: not found on Tidal")
        verification["playlists"].append(entry)

    pl_expected = sum(p["expected_tracks"] for p in verification["playlists"])
    pl_present = sum(p["present"] for p in verification["playlists"])
    verification["summary"] = {
        "liked_health": verification["liked_tracks"]["health"],
        "playlist_track_health": f"{pct(pl_present, pl_expected)}%",
        "playlists_found": sum(1 for p in verification["playlists"] if p["found_on_tidal"]),
        "playlists_total": len(verification["playlists"]),
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(verification, f, indent=2)

    print("\n" + "=" * 60)
    print("  Verification Complete")
    print("=" * 60)
    s = verification["summary"]
    print(f"  Liked tracks health:   {s['liked_health']} "
          f"({verification['liked_tracks']['present']}/{verification['liked_tracks']['expected']})")
    print(f"  Playlist track health: {s['playlist_track_health']} ({pl_present}/{pl_expected})")
    print(f"  Playlists found:       {s['playlists_found']}/{s['playlists_total']}")
    print(f"  Saved to: {output_path}")


if __name__ == "__main__":
    main()
