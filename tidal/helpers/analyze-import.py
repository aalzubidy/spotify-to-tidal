#!/usr/bin/env python3
"""
Tidal Import Analyzer — exact ISRC/barcode matching via the official v2 API.

Strategy (replaces the old fuzzy "album-first" engine):
  1. Collect every unique ISRC from liked + playlist tracks.
  2. Batch-resolve them with GET /tracks?filter[isrc]=...  (exact, no guessing).
  3. Capped text-search fallback for ISRCs Tidal didn't return.
  4. Albums: exact UPC barcode match (if export has UPC), else derive album IDs
     from matched tracks, else fuzzy album search.
  5. Artists: text search by name.

Everything is written to a PERSISTENT, RESUMABLE cache (tidal-match-cache.json)
in the working directory. Killing the run and re-running picks up where it left
off — no repeated API calls. import-all.py reads this cache as its source of truth.

Usage:
    python3 analyze-import.py <SPOTIFY_EXPORT_JSON> <WORK_DIR> <ANALYSIS_OUTPUT_JSON>
        [--batch N] [--fallback-cap N] [--no-fallback] [--limit N]
"""

import sys
sys.dont_write_bytecode = True
import json
import os
import time

from tidal_openapi import TidalOpenAPI

CACHE_FILENAME = "tidal-match-cache.json"
DEFAULT_ISRC_BATCH = 20          # ISRCs per /tracks?filter[isrc] request
DEFAULT_FALLBACK_CAP = 2000      # max text-search fallbacks per run (rate-limit guard)
SAVE_EVERY = 25                  # persist cache every N batches


# Matching helpers

def fuzzy_score(s1, s2):
    """Levenshtein-ratio similarity in [0,1]."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return 1 - (prev[-1] / max_len)


# Cache

def empty_cache():
    return {
        "tracks": {},        # ISRC -> {tidal_id, album_id, artist_ids, title, method}
        "track_misses": {},  # ISRC -> true  (not found by ISRC lookup)
        "fallback_done": {}, # ISRC -> true  (text fallback attempted)
        "albums": {},        # spotify_album_id -> {tidal_album_id, method}
        "album_misses": {},
        "artists": {},       # spotify_artist_id -> {tidal_artist_id, name, method}
        "artist_misses": {},
    }


def load_cache(path):
    if os.path.exists(path):
        try:
            c = json.load(open(path))
            for k in empty_cache():
                c.setdefault(k, {})
            return c
        except (ValueError, OSError):
            pass
    return empty_cache()


def save_cache(path, cache):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, path)


# Collection

def collect_unique_isrcs(sp):
    """Return {ISRC: {name, artist}} for one representative track per ISRC."""
    uniq = {}

    def add(t):
        isrc = (t.get("isrc") or "").upper().strip()
        if not isrc or isrc in uniq:
            return
        artists = t.get("artists", [])
        artist = ""
        if artists:
            a0 = artists[0]
            artist = a0.get("name") or a0.get("artist_name") or ""
        uniq[isrc] = {"name": t.get("name", ""), "artist": artist}

    for t in sp.get("liked_tracks", []):
        add(t)
    for pl in sp.get("playlists", []):
        for t in pl.get("tracks", []):
            add(t)
    return uniq


# Phase: ISRC matching

def match_isrcs(client, uniq_isrcs, cache, cache_path, batch_size):
    pending = [i for i in uniq_isrcs
               if i not in cache["tracks"] and i not in cache["track_misses"]]
    total = len(pending)
    print(f"\n[ISRC match] {total} new ISRCs to resolve "
          f"({len(cache['tracks'])} already cached)")
    if not total:
        return

    batches = 0
    for start in range(0, total, batch_size):
        chunk = pending[start:start + batch_size]
        found = client.tracks_by_isrc(chunk)
        for isrc in chunk:
            if isrc in found:
                f = found[isrc]
                cache["tracks"][isrc] = {
                    "tidal_id": f["tidal_id"],
                    "album_id": f.get("album_id"),
                    "artist_ids": f.get("artist_ids", []),
                    "title": f.get("title", ""),
                    "method": "isrc",
                }
            else:
                cache["track_misses"][isrc] = True
        batches += 1
        if batches % SAVE_EVERY == 0:
            save_cache(cache_path, cache)
        done = min(start + batch_size, total)
        if batches % 10 == 0 or done == total:
            print(f"    {done}/{total}  (matched {len(cache['tracks'])}, "
                  f"misses {len(cache['track_misses'])})")
    save_cache(cache_path, cache)


# Phase: text fallback for ISRC misses

def fallback_search(client, uniq_isrcs, cache, cache_path, cap):
    candidates = [i for i in cache["track_misses"]
                  if i not in cache["tracks"] and i not in cache["fallback_done"]]
    if not candidates:
        print("\n[Fallback] nothing to do")
        return
    capped = candidates[:cap]
    skipped = len(candidates) - len(capped)
    print(f"\n[Fallback] text-searching {len(capped)} ISRC misses"
          + (f" (capping — {skipped} left for a later run)" if skipped else ""))

    done = 0
    for isrc in capped:
        info = uniq_isrcs.get(isrc, {})
        name, artist = info.get("name", ""), info.get("artist", "")
        cache["fallback_done"][isrc] = True
        if name:
            query = (name + " " + artist).strip()
            best, best_score = None, 0.0
            for r in client.search_tracks(query, limit=5):
                score = fuzzy_score(name, r["title"])
                if r.get("isrc") and r["isrc"] == isrc:
                    score = 1.0
                if score > best_score:
                    best_score, best = score, r
            if best and best_score >= 0.78:
                cache["tracks"][isrc] = {
                    "tidal_id": best["tidal_id"],
                    "album_id": None,
                    "artist_ids": best.get("artist_ids", []),
                    "title": best.get("title", ""),
                    "method": "search",
                }
        done += 1
        if done % SAVE_EVERY == 0:
            save_cache(cache_path, cache)
        if done % 50 == 0 or done == len(capped):
            print(f"    {done}/{len(capped)}  (recovered "
                  f"{sum(1 for v in cache['tracks'].values() if v['method']=='search')})")
    save_cache(cache_path, cache)


# Phase: albums

def match_albums(client, sp, cache, cache_path):
    saved = sp.get("saved_albums", [])
    print(f"\n[Albums] {len(saved)} saved albums")
    # 1) exact UPC barcode match for albums whose export carries a UPC
    upc_to_sid = {}
    for a in saved:
        sid = a.get("spotify_id") or a.get("id")
        upc = (a.get("upc") or "").strip()
        if sid and upc and sid not in cache["albums"]:
            upc_to_sid[upc] = sid
    if upc_to_sid:
        upcs = list(upc_to_sid)
        for i in range(0, len(upcs), 20):
            chunk = upcs[i:i + 20]
            found = client.albums_by_barcode(chunk)
            for upc in chunk:
                sid = upc_to_sid[upc]
                if upc in found:
                    cache["albums"][sid] = {"tidal_album_id": found[upc]["tidal_album_id"],
                                            "method": "barcode"}
        save_cache(cache_path, cache)

    # 2) fuzzy fallback for saved albums still unmatched (e.g. export had no UPC)
    for a in saved:
        sid = a.get("spotify_id") or a.get("id")
        if not sid or sid in cache["albums"] or sid in cache["album_misses"]:
            continue
        name = a.get("name", "")
        artists = [ar.get("name", "") for ar in a.get("artists", [])]
        query = (name + " " + (artists[0] if artists else "")).strip()
        best, best_score = None, 0.0
        for r in client.search_albums(query, limit=5):
            s = fuzzy_score(name, r["title"])
            if s > best_score:
                best_score, best = s, r
        if best and best_score >= 0.6:
            cache["albums"][sid] = {"tidal_album_id": best["tidal_id"], "method": "fuzzy"}
        else:
            cache["album_misses"][sid] = True
    save_cache(cache_path, cache)
    print(f"    matched {len(cache['albums'])}, misses {len(cache['album_misses'])}")


# Phase: artists

def match_artists(client, sp, cache, cache_path):
    artists = sp.get("followed_artists", [])
    print(f"\n[Artists] {len(artists)} followed artists")
    for a in artists:
        sid = a.get("spotify_id") or a.get("id")
        if not sid or sid in cache["artists"] or sid in cache["artist_misses"]:
            continue
        name = (a.get("name") or "").strip()
        best, best_score = None, 0.0
        for r in client.search_artists(name, limit=5):
            s = fuzzy_score(name, r["name"])
            if s > best_score:
                best_score, best = s, r
        if best and best_score >= 0.6:
            cache["artists"][sid] = {"tidal_artist_id": best["tidal_id"],
                                     "name": best["name"], "method": "search"}
        else:
            cache["artist_misses"][sid] = True
    save_cache(cache_path, cache)
    print(f"    matched {len(cache['artists'])}, misses {len(cache['artist_misses'])}")


# Summary

def write_summary(sp, cache, uniq_isrcs, output_path):
    total_tracks = len(uniq_isrcs)
    matched_tracks = sum(1 for i in uniq_isrcs if i in cache["tracks"])
    by_isrc = sum(1 for v in cache["tracks"].values() if v["method"] == "isrc")
    by_search = sum(1 for v in cache["tracks"].values() if v["method"] == "search")
    playlists = []
    for pl in sp.get("playlists", []):
        tot = len(pl.get("tracks", []))
        m = sum(1 for t in pl.get("tracks", [])
                if (t.get("isrc") or "").upper().strip() in cache["tracks"])
        playlists.append({"name": pl.get("name"), "total": tot, "matched": m,
                          "rate": f"{(100*m/tot if tot else 100):.1f}%"})
    summary = {
        "analyzed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "official_v2_isrc_exact",
        "tracks": {
            "unique_isrcs": total_tracks,
            "matched": matched_tracks,
            "by_isrc": by_isrc,
            "by_search_fallback": by_search,
            "unmatched": total_tracks - matched_tracks,
            "match_rate": f"{(100*matched_tracks/total_tracks if total_tracks else 100):.1f}%",
        },
        "albums": {"saved": len(sp.get("saved_albums", [])),
                   "matched": len(cache["albums"])},
        "artists": {"followed": len(sp.get("followed_artists", [])),
                    "matched": len(cache["artists"])},
        "playlists": playlists,
    }
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    return summary


def main():
    args = sys.argv[1:]
    pos, batch, cap, do_fallback, limit = [], DEFAULT_ISRC_BATCH, DEFAULT_FALLBACK_CAP, True, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--batch":
            i += 1; batch = int(args[i])
        elif a == "--fallback-cap":
            i += 1; cap = int(args[i])
        elif a == "--no-fallback":
            do_fallback = False
        elif a == "--limit":
            i += 1; limit = int(args[i])
        else:
            pos.append(a)
        i += 1

    if len(pos) < 3:
        print(f"Usage: {sys.argv[0]} <SPOTIFY_EXPORT_JSON> <WORK_DIR> <ANALYSIS_OUTPUT_JSON> "
              f"[--batch N] [--fallback-cap N] [--no-fallback] [--limit N]", file=sys.stderr)
        sys.exit(1)
    spotify_path, work_dir, output_path = pos[0], pos[1], pos[2]

    print("=" * 60)
    print("  Tidal Import Analyzer — official v2 ISRC matching")
    print("=" * 60)

    sp = json.load(open(spotify_path))
    client = TidalOpenAPI(work_dir)
    if not client.is_authenticated():
        print("\n  ERROR: not authenticated to the official Tidal API.")
        print(f"  Run:  python3 tidal_openapi.py {work_dir} auth\n", file=sys.stderr)
        sys.exit(2)

    cache_path = os.path.join(work_dir, CACHE_FILENAME)
    cache = load_cache(cache_path)

    uniq = collect_unique_isrcs(sp)
    if limit:
        uniq = dict(list(uniq.items())[:limit])
        print(f"  (--limit {limit}: testing on {len(uniq)} ISRCs)")

    match_isrcs(client, uniq, cache, cache_path, batch)
    if do_fallback:
        fallback_search(client, uniq, cache, cache_path, cap)
    match_albums(client, sp, cache, cache_path)
    match_artists(client, sp, cache, cache_path)

    summary = write_summary(sp, cache, uniq, output_path)

    print("\n" + "=" * 60)
    print("  Analysis Complete")
    print("=" * 60)
    t = summary["tracks"]
    print(f"  Tracks:  {t['matched']}/{t['unique_isrcs']} ({t['match_rate']})  "
          f"[isrc {t['by_isrc']}, search {t['by_search_fallback']}]")
    print(f"  Albums:  {summary['albums']['matched']}/{summary['albums']['saved']}")
    print(f"  Artists: {summary['artists']['matched']}/{summary['artists']['followed']}")
    print(f"  Cache:   {cache_path}")
    print(f"  Summary: {output_path}")


if __name__ == "__main__":
    main()
