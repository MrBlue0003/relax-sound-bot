#!/usr/bin/env python3
"""save_log.py — Safely push uploaded.json with automatic conflict resolution.

Problem: 4 daily runs start at the same cron time. They all checkout the same
base commit, build their video (~2-3 min), then all try to push uploaded.json
at nearly the same time. git pull --rebase fails with a JSON merge conflict.

Solution: fetch remote → merge both JSON arrays → reset to remote HEAD →
commit merged → push. Retry up to 5× with back-off for concurrent pushes.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

LOG       = Path("logs/uploaded.json")
PLAYLISTS = Path("data/playlists.json")


def git(*args, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"git {' '.join(args)} failed:\n{r.stderr}", file=sys.stderr)
        raise SystemExit(1)
    return r


def main() -> int:
    # 1. Read local version — contains our freshly-added entry
    if not LOG.exists():
        print("No upload log found, nothing to save")
        return 0

    with open(LOG, encoding="utf-8") as f:
        local_data = json.load(f)

    local_uploads = local_data.get("uploads", [])
    if not local_uploads:
        print("Upload log is empty, nothing to save")
        return 0

    our_entry = local_uploads[-1]   # the entry we just added this run
    our_id    = our_entry.get("video_id", "")
    print(f"Saving entry: {our_id} — {our_entry.get('title','')[:60]}")

    for attempt in range(1, 6):
        # 2. Fetch latest remote state
        git("fetch", "origin", "main")

        # 3. Read remote uploaded.json
        r = git("show", "origin/main:logs/uploaded.json", check=False)
        if r.returncode == 0:
            try:
                remote_data    = json.loads(r.stdout)
                remote_uploads = remote_data.get("uploads", [])
            except json.JSONDecodeError:
                remote_uploads = []
        else:
            remote_uploads = []

        # 4. If our entry is already there (another run beat us), done
        remote_ids = {u.get("video_id") for u in remote_uploads}
        if our_id and our_id in remote_ids:
            print("Entry already in remote log — no push needed")
            return 0

        # 5. Merge: remote entries + our new entry
        merged = {"uploads": remote_uploads + [our_entry]}
        with open(LOG, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)

        # 6. Reset local HEAD to remote and commit the merged file
        git("reset", "--soft", "origin/main")
        git("add", str(LOG))
        # Also stage playlists.json — may have gained new playlist IDs this run
        if PLAYLISTS.exists():
            git("add", str(PLAYLISTS))

        diff = git("diff", "--staged", "--quiet", check=False)
        if diff.returncode == 0:
            print("Nothing staged after merge, already up to date")
            return 0

        git("commit", "-m", "chore: update upload log [skip ci]")

        # 7. Push — may fail if another run pushed between our fetch and now
        push = git("push", check=False)
        if push.returncode == 0:
            print(f"Upload log pushed (attempt {attempt})")
            return 0

        wait = attempt * 3
        print(f"Push failed (attempt {attempt}/5) — retrying in {wait}s …")
        time.sleep(wait)

    print("ERROR: could not push upload log after 5 attempts")
    return 1


if __name__ == "__main__":
    sys.exit(main())
