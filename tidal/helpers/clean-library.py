#!/usr/bin/env python3
"""
Tidal Library Cleaner — official v2 API

Selectively empties Tidal library categories (tracks, albums, artists, playlists)
before a fresh re-import. Reads the current account state via the official API
and removes items in batches (50/request) with steady pacing + Retry-After.

Usage:
    # Dry run — show what would be deleted:
    python3 clean-library.py <WORK_DIR> --categories tracks,albums,artists,playlists

    # Actually delete (typed confirmation required):
    python3 clean-library.py <WORK_DIR> --categories tracks,albums,artists,playlists --confirm
"""

import sys
sys.dont_write_bytecode = True

from tidal_openapi import TidalOpenAPI

VALID = {"tracks", "albums", "artists", "playlists"}


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <WORK_DIR> --categories tracks,albums,artists,playlists [--confirm]",
              file=sys.stderr)
        sys.exit(1)

    work_dir = sys.argv[1]
    categories, confirmed = [], False
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--categories" and i + 1 < len(sys.argv):
            categories = [c.strip().lower() for c in sys.argv[i + 1].split(",")]
            i += 2
        elif sys.argv[i] == "--confirm":
            confirmed = True
            i += 1
        else:
            i += 1

    for c in categories:
        if c not in VALID:
            print(f"  Invalid category: {c}. Valid: {', '.join(sorted(VALID))}", file=sys.stderr)
            sys.exit(1)
    if not categories:
        print("  No categories specified. Use --categories.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  Tidal Library Cleaner — official v2 API")
    print("=" * 60)
    print(f"  Categories: {', '.join(categories)}\n")

    client = TidalOpenAPI(work_dir)
    if not client.is_authenticated():
        print(f"  ERROR: not authenticated. Run: python3 tidal_openapi.py {work_dir} auth", file=sys.stderr)
        sys.exit(2)

    # Fetch current state
    state = {}
    for cat in categories:
        if cat == "playlists":
            pls = client.get_user_playlists()
            state[cat] = pls
            print(f"  playlists: {len(pls)}")
        else:
            ids = client.get_collection_ids(cat)
            state[cat] = list(ids)
            print(f"  {cat}: {len(ids)}")

    if not confirmed:
        print("\n  Mode: DRY RUN — run with --confirm to delete.")
        sys.exit(0)

    print("\n  WARNING: this permanently removes the above items from your Tidal library.")
    if input("  Type 'yes delete everything' to confirm: ").strip().lower() != "yes delete everything":
        print("  Aborted.")
        sys.exit(1)

    print("\n[Deleting]")
    for cat in categories:
        if cat == "playlists":
            deleted = failed = 0
            for pl in state[cat]:
                if client.delete_playlist(pl["id"]):
                    deleted += 1
                else:
                    failed += 1
            print(f"  playlists: {deleted} deleted, {failed} failed")
        else:
            removed, failed = client.remove_favorites(cat, state[cat])
            print(f"  {cat}: {removed} removed, {failed} failed")

    print("\n  Cleanup complete.")


if __name__ == "__main__":
    main()
