"""github_log.py — Persist uploaded.json to GitHub via REST API.

Railway containers are ephemeral — logs/uploaded.json is lost on each restart.
This module pulls the log from GitHub at startup and pushes it back after upload,
so the rotation and dedup logic work correctly across runs.

Requires:
    GH_PAT  — GitHub Personal Access Token (repo write scope)
    GH_REPO — e.g. "MrBlue0003/relax-sound-bot" (default hardcoded)
"""
import base64
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger(__name__)

_GITHUB_TOKEN = os.getenv("GH_PAT", "")
_REPO = os.getenv("GH_REPO", "MrBlue0003/relax-sound-bot")
_FILE_PATH = "logs/uploaded.json"
_BRANCH = "main"
_API_URL = f"https://api.github.com/repos/{_REPO}/contents/{_FILE_PATH}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "relax-sound-bot",
    }


def pull_log(local_path: Path) -> None:
    """Download uploaded.json from GitHub to local disk.

    If the file doesn't exist in GitHub yet (first ever run),
    starts fresh — no error.
    """
    if not _GITHUB_TOKEN:
        logger.warning(
            "GH_PAT not set — skipping log pull. "
            "Add GH_PAT to Railway env vars for dedup to work across runs."
        )
        return

    req = urllib.request.Request(
        f"{_API_URL}?ref={_BRANCH}", headers=_headers()
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        content = base64.b64decode(data["content"]).decode("utf-8")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")

        n = len(json.loads(content).get("uploads", []))
        logger.info(f"Pulled uploaded.json from GitHub — {n} previous uploads loaded")

    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.info("uploaded.json not yet in GitHub — starting fresh (first run)")
        else:
            logger.warning(f"GitHub pull failed (HTTP {e.code}): {e.reason}")
    except Exception as e:
        logger.warning(f"GitHub pull failed (non-fatal): {e}")


def push_log(local_path: Path) -> None:
    """Upload updated uploaded.json back to GitHub.

    Gets the current file SHA first (required for GitHub update API),
    then PUTs the new content.
    """
    if not _GITHUB_TOKEN:
        return
    if not local_path.exists():
        return

    content = local_path.read_text(encoding="utf-8")
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    # Get current file SHA (needed for update; None if file doesn't exist yet)
    sha = None
    req = urllib.request.Request(
        f"{_API_URL}?ref={_BRANCH}", headers=_headers()
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            sha = json.loads(resp.read()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logger.warning(f"Could not get file SHA: {e}")
    except Exception as e:
        logger.warning(f"Could not get file SHA: {e}")

    body: dict = {
        "message": "chore: update upload log [skip ci]",
        "content": encoded,
        "branch": _BRANCH,
    }
    if sha:
        body["sha"] = sha

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        _API_URL, data=payload, headers=_headers(), method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("Pushed uploaded.json to GitHub ✓")
    except Exception as e:
        logger.warning(f"GitHub push failed (non-fatal — log may be lost): {e}")
