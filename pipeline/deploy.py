#!/usr/bin/env python3
"""
deploy.py — push built listing files to GitHub via the Contents API.

This repo does NOT auto-deploy from a git push, so files go up through the API
one at a time. The SHA of an existing file is fetched fresh immediately before
its PUT (a stale SHA is the usual cause of a 409), and transient 5xx responses
are retried with a ~4 second backoff.

Usage:
    GITHUB_TOKEN=ghp_xxx python3 pipeline/deploy.py isla nadia apolline rosalie
    GITHUB_TOKEN=ghp_xxx python3 pipeline/deploy.py isla --dry-run

Slugs push <slug>/index.html, <slug>/plan.html and <slug>/thumb.jpg. The shared
gallery files (index.html, units.json) go up once at the end, after the unit
pages exist, so the gallery never links to a page that isn't live yet.
"""
import argparse, base64, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

REPO = os.environ.get("SANDERS_REPO", "armanpaknahad-debug/sanders-albania-listings")
BRANCH = os.environ.get("SANDERS_BRANCH", "main")
API = f"https://api.github.com/repos/{REPO}/contents/"
RETRY_STATUS = {500, 502, 503, 504}
BACKOFF = 4.0
MAX_TRIES = 5


def _req(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sanders-deploy",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(r, timeout=120) as resp:
        return resp.status, json.loads(resp.read() or b"{}")


def get_sha(path, token):
    """Current blob SHA for path on BRANCH, or None if the file is new."""
    url = f"{API}{path}?ref={BRANCH}"
    for attempt in range(1, MAX_TRIES + 1):
        try:
            _, body = _req("GET", url, token)
            return body.get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 401:
                raise SystemExit("HTTP 401: the token is invalid, expired or revoked.")
            if e.code == 403:
                want = e.headers.get("x-accepted-github-permissions", "contents=write")
                raise SystemExit(f"HTTP 403: token lacks the required permission ({want}).")
            if e.code in RETRY_STATUS and attempt < MAX_TRIES:
                time.sleep(BACKOFF); continue
            raise
        except urllib.error.URLError:
            if attempt < MAX_TRIES:
                time.sleep(BACKOFF); continue
            raise
    return None


def put_file(local: Path, path: str, token: str, message: str, dry=False):
    content = base64.b64encode(local.read_bytes()).decode()
    size_kb = local.stat().st_size // 1024
    if dry:
        print(f"  [dry-run] {path}  ({size_kb} KB)")
        return "dry-run"
    for attempt in range(1, MAX_TRIES + 1):
        sha = get_sha(path, token)          # fetched fresh, immediately before the PUT
        payload = {"message": message, "content": content, "branch": BRANCH}
        if sha:
            payload["sha"] = sha
        try:
            _, body = _req("PUT", f"{API}{path}", token, payload)
            action = "updated" if sha else "created"
            print(f"  {action} {path}  ({size_kb} KB)  {body['content']['sha'][:8]}")
            return action
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:200]
            if e.code == 409 and attempt < MAX_TRIES:
                print(f"  409 conflict on {path}, refetching SHA (attempt {attempt})")
                time.sleep(BACKOFF); continue
            if e.code in RETRY_STATUS and attempt < MAX_TRIES:
                print(f"  {e.code} on {path}, retrying in {BACKOFF:.0f}s (attempt {attempt})")
                time.sleep(BACKOFF); continue
            raise SystemExit(f"FAILED {path}: HTTP {e.code} {detail}")
        except urllib.error.URLError as e:
            if attempt < MAX_TRIES:
                print(f"  network error on {path} ({e.reason}), retrying in {BACKOFF:.0f}s")
                time.sleep(BACKOFF); continue
            raise
    raise SystemExit(f"FAILED {path}: retries exhausted")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", help="unit slugs to push")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    ap.add_argument("--extra", nargs="*", default=[], help="additional repo-relative paths")
    ap.add_argument("--delete", nargs="*", default=[], help="repo-relative paths to delete")
    ap.add_argument("--message", help="commit message")
    ap.add_argument("--no-gallery", action="store_true", help="skip index.html + units.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.token and not args.dry_run:
        raise SystemExit("No token. Pass --token or set GITHUB_TOKEN.")

    root = Path(__file__).resolve().parent.parent
    files = []
    for slug in args.slugs:
        for name in ("index.html", "plan.html", "thumb.jpg"):
            p = root / slug / name
            if p.exists():
                files.append((p, f"{slug}/{name}"))
            else:
                print(f"  ! missing {slug}/{name}, skipping")
    for extra in args.extra:
        p = root / extra
        if not p.exists():
            raise SystemExit(f"missing extra file: {extra}")
        files.append((p, extra))
    # gallery last: the cards must not go live before the pages they link to
    if not args.no_gallery:
        for name in ("index.html", "units.json"):
            files.append((root / name, name))

    label = ", ".join(args.slugs) or "files"
    message = args.message or f"Add {label} to the Sanders Albania collection"
    print(f"Pushing {len(files)} files to {REPO}@{BRANCH}")
    for local, path in files:
        put_file(local, path, args.token, message, dry=args.dry_run)
    for path in args.delete:
        delete_file(path, args.token, message, dry=args.dry_run)
    print("\nDone.")
    for slug in args.slugs:
        print(f"  https://listings.sandersalbania.com/{slug}/")


def delete_file(path, token, message, dry=False):
    if dry:
        print(f"  [dry-run] DELETE {path}")
        return
    for attempt in range(1, MAX_TRIES + 1):
        sha = get_sha(path, token)
        if sha is None:
            print(f"  already gone {path}")
            return
        try:
            data = json.dumps({"message": message, "sha": sha, "branch": BRANCH}).encode()
            r = urllib.request.Request(f"{API}{path}", data=data, method="DELETE", headers={
                "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "sanders-deploy",
                "Content-Type": "application/json"})
            with urllib.request.urlopen(r, timeout=120):
                print(f"  deleted {path}")
            return
        except urllib.error.HTTPError as e:
            if e.code == 409 and attempt < MAX_TRIES:
                time.sleep(BACKOFF); continue
            raise SystemExit(f"FAILED delete {path}: HTTP {e.code} {e.read().decode()[:150]}")


if __name__ == "__main__":
    main()
