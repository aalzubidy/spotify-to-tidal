#!/usr/bin/env python3
"""
Tidal Music Importer (official v2 API — openapi.tidal.com/v2)

Reads the Spotify export + the resumable match cache produced by
analyze-import.py (tidal-match-cache.json) and writes everything to Tidal:
liked tracks, saved albums, followed artists, and playlists (tracks added in
Spotify order). All matches come from the cache — NO live matching here, and
NO 500-item truncation (the old bug that capped imports at 500 tracks).

Usage:
    python3 import-all.py <SPOTIFY_EXPORT_JSON> <WORK_DIR> <OUTPUT_JSON>
        [--no-albums] [--no-artists] [--no-playlists] [--no-liked] [--no-liked-playlist]
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


def main():
    args = sys.argv[1:]
    pos = []
    do = {"liked": True, "albums": True, "artists": True, "playlists": True, "liked_playlist": True}
    for a in args:
        if a == "--no-liked":
            do["liked"] = False
        elif a == "--no-albums":
            do["albums"] = False
        elif a == "--no-artists":
            do["artists"] = False
        elif a == "--no-playlists":
            do["playlists"] = False
        elif a == "--no-liked-playlist":
            do["liked_playlist"] = False
        else:
            pos.append(a)

    if len(pos) < 3:
        print(f"Usage: {sys.argv[0]} <SPOTIFY_EXPORT_JSON> <WORK_DIR> <OUTPUT_JSON> "
              f"[--no-liked] [--no-albums] [--no-artists] [--no-playlists] [--no-liked-playlist]",
              file=sys.stderr)
        sys.exit(1)
    spotify_path, work_dir, output_path = pos[0], pos[1], pos[2]

    print("=" * 60)
    print("  Tidal Importer — official v2 API")
    print("=" * 60)

    sp = json.load(open(spotify_path))
    cache_path = os.path.join(work_dir, CACHE_FILENAME)
    if not os.path.exists(cache_path):
        print(f"\n  ERROR: match cache not found: {cache_path}")
        print("  Run analyze-import.py first.\n", file=sys.stderr)
        sys.exit(2)
    cache = json.load(open(cache_path))
    track_map = cache.get("tracks", {})          # ISRC -> {tidal_id, album_id, artist_ids}
    album_map = cache.get("albums", {})          # spotify_album_id -> {tidal_album_id}
    artist_map = cache.get("artists", {})        # spotify_artist_id -> {tidal_artist_id}

    client = TidalOpenAPI(work_dir)
    if not client.is_authenticated():
        print("\n  ERROR: not authenticated to Tidal.")
        print(f"  Run:  python3 tidal_openapi.py {work_dir} auth\n", file=sys.stderr)
        sys.exit(2)

    result = {
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api": "official_v2",
        "liked_tracks": {"imported": 0, "failed": 0},
        "albums": {"imported": 0, "failed": 0},
        "artists": {"imported": 0, "failed": 0},
        "playlists": [],
    }

    # ---- Liked tracks ----
    if do["liked"]:
        liked_ids, seen = [], set()
        for t in sp.get("liked_tracks", []):
            m = track_map.get(isrc_of(t))
            if m and m["tidal_id"] not in seen:
                seen.add(m["tidal_id"])
                liked_ids.append(m["tidal_id"])
        print(f"\n[Liked tracks] {len(liked_ids)} matched of {len(sp.get('liked_tracks', []))}")
        added, failed, errors = client.add_favorites("tracks", liked_ids)
        result["liked_tracks"] = {"imported": added, "failed": failed}
        print(f"  imported {added}, failed {failed}")
        if errors:
            print("  sample errors:", errors)

    # ---- Albums (saved albums matched + albums of matched tracks) ----
    if do["albums"]:
        album_ids = set()
        for m in album_map.values():
            if m.get("tidal_album_id"):
                album_ids.add(str(m["tidal_album_id"]))
        for m in track_map.values():
            if m.get("album_id"):
                album_ids.add(str(m["album_id"]))
        album_ids = list(album_ids)
        print(f"\n[Albums] {len(album_ids)} unique Tidal albums")
        added, failed, errors = client.add_favorites("albums", album_ids)
        result["albums"] = {"imported": added, "failed": failed}
        print(f"  imported {added}, failed {failed}")
        if errors:
            print("  sample errors:", errors)

    # ---- Artists (followed matched + artists of matched tracks) ----
    if do["artists"]:
        artist_ids = set()
        for m in artist_map.values():
            if m.get("tidal_artist_id"):
                artist_ids.add(str(m["tidal_artist_id"]))
        for m in track_map.values():
            for aid in m.get("artist_ids", []):
                if aid:
                    artist_ids.add(str(aid))
        artist_ids = list(artist_ids)
        print(f"\n[Artists] {len(artist_ids)} unique Tidal artists")
        added, failed, errors = client.add_favorites("artists", artist_ids)
        result["artists"] = {"imported": added, "failed": failed}
        print(f"  imported {added}, failed {failed}")
        if errors:
            print("  sample errors:", errors)

    # ---- Playlists (recreate, tracks in Spotify order) ----
    if do["playlists"]:
        playlists = sp.get("playlists", [])
        print(f"\n[Playlists] {len(playlists)}")
        for idx, pl in enumerate(playlists):
            name = pl.get("name", "Untitled")
            access = "PUBLIC" if pl.get("public") else "UNLISTED"
            # Resolve track IDs in order, dropping unmatched (keeps relative order)
            track_ids, unmatched = [], 0
            for t in pl.get("tracks", []):
                m = track_map.get(isrc_of(t))
                if m:
                    track_ids.append(m["tidal_id"])
                else:
                    unmatched += 1
            pid = client.create_playlist(name, pl.get("description", ""), access=access)
            pl_res = {"name": name, "tidal_playlist_id": pid,
                      "tracks_total": len(pl.get("tracks", [])),
                      "tracks_imported": 0, "tracks_failed": 0,
                      "tracks_unmatched": unmatched}
            if not pid:
                pl_res["status"] = "create_failed"
                print(f"  [{idx+1}/{len(playlists)}] {name}: FAILED to create")
                result["playlists"].append(pl_res)
                continue
            added, failed = client.add_playlist_items(pid, track_ids)
            pl_res["tracks_imported"] = added
            pl_res["tracks_failed"] = failed
            pl_res["status"] = "imported" if failed == 0 else "partial"
            print(f"  [{idx+1}/{len(playlists)}] {name}: {added}/{len(pl.get('tracks', []))} "
                  f"added (unmatched {unmatched}, failed {failed})")
            result["playlists"].append(pl_res)

    # ---- Liked Songs playlist (ordered duplicate of liked tracks, for browsability) ----
    if do["liked_playlist"]:
        liked_ids_ordered, seen_lp = [], set()
        for t in sp.get("liked_tracks", []):
            m = track_map.get(isrc_of(t))
            if m and m["tidal_id"] not in seen_lp:
                seen_lp.add(m["tidal_id"])
                liked_ids_ordered.append(m["tidal_id"])
        print(f"\n[Liked Songs playlist] {len(liked_ids_ordered)} tracks")
        lp_id = client.create_playlist(
            "Liked Songs",
            "Your Spotify liked songs, in order",
            access="UNLISTED",
        )
        lp_res = {
            "name": "Liked Songs",
            "tidal_playlist_id": lp_id,
            "tracks_total": len(liked_ids_ordered),
            "tracks_imported": 0, "tracks_failed": 0,
            "tracks_unmatched": 0, "status": "liked_songs",
        }
        if lp_id:
            added, failed = client.add_playlist_items(lp_id, liked_ids_ordered)
            lp_res["tracks_imported"] = added
            lp_res["tracks_failed"] = failed
            lp_res["status"] = "imported" if failed == 0 else "partial"
            print(f"  created {lp_id}: {added}/{len(liked_ids_ordered)} added, {failed} failed")
        else:
            print("  FAILED to create Liked Songs playlist")
        result["playlists"].append(lp_res)

    # ---- Summary ----
    pl_imported = sum(p["tracks_imported"] for p in result["playlists"])
    result["summary"] = {
        "liked_imported": result["liked_tracks"]["imported"],
        "albums_imported": result["albums"]["imported"],
        "artists_imported": result["artists"]["imported"],
        "playlists_created": sum(1 for p in result["playlists"] if p.get("tidal_playlist_id")),
        "playlist_tracks_imported": pl_imported,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print("\n" + "=" * 60)
    print("  Import Complete")
    print("=" * 60)
    s = result["summary"]
    print(f"  Liked tracks:    {s['liked_imported']}")
    print(f"  Albums:          {s['albums_imported']}")
    print(f"  Artists:         {s['artists_imported']}")
    print(f"  Playlists:       {s['playlists_created']} created, "
          f"{s['playlist_tracks_imported']} tracks added")
    print(f"  Saved to: {output_path}")


if __name__ == "__main__":
    main()
