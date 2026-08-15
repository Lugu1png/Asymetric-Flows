"""Step 1: download the quarterly N-PORT zips and record a checksum manifest.

Usage:  SEC_USER_AGENT="Your Name you@uni.lu" python -m nportflows.download
"""
import hashlib
import json
import time
import zipfile
from datetime import datetime, timezone

import requests

from . import config as C

RETRY_STATUS = {403, 429, 500, 502, 503, 504}   # SEC answers 403 when throttling


def sha256(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(block), b""):
            h.update(b)
    return h.hexdigest()


def fetch(s, url, tmp, tries=C.DOWNLOAD_TRIES):
    """Download url to tmp with retries. Returns the zip member list, or None on 404."""
    for attempt in range(1, tries + 1):
        try:
            with s.get(url, stream=True, timeout=120) as r:
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            with zipfile.ZipFile(tmp) as zf:             # fails loudly on a truncated file
                return zf.namelist()
        except (requests.RequestException, zipfile.BadZipFile) as e:
            tmp.unlink(missing_ok=True)
            status = getattr(getattr(e, "response", None), "status_code", None)
            if attempt == tries or (status and 400 <= status < 500
                                               and status not in RETRY_STATUS):
                raise                                    # e.g. 400/401: retrying won't help
            wait = 10 * 2 ** (attempt - 1)
            print(f"  attempt {attempt} failed ({e}); retrying in {wait}s")
            time.sleep(wait)


def main():
    """Download every missing quarter. Returns the list of quarters newly downloaded."""
    if not C.USER_AGENT or "@" not in C.USER_AGENT:
        raise SystemExit("Set SEC_USER_AGENT to 'Name email@domain' (SEC fair-access policy).")
    C.RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = C.RAW / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    s = requests.Session()
    s.headers.update({"User-Agent": C.USER_AGENT, "Accept-Encoding": "gzip, deflate"})

    new = []
    for q in C.quarters():
        dest = C.RAW / f"{q}_nport.zip"
        if dest.exists() and q in manifest and manifest[q]["sha256"] == sha256(dest):
            print(f"{q}: present, checksum ok")
            continue
        url = C.BASE_URL.format(q=q)
        print(f"{q}: downloading {url}")
        tmp = dest.with_suffix(".part")
        recent = C.maybe_unpublished(q)
        try:
            members = fetch(s, url, tmp, tries=1 if recent else C.DOWNLOAD_TRIES)
        except requests.HTTPError as e:
            if not recent:
                raise
            members = None
            print(f"{q}: HTTP {e.response.status_code}; probably not published yet")
        if members is None:
            print(f"{q}: not published yet, skipping (a later run will pick it up)")
            continue
        tmp.replace(dest)                            # replace(): rename() fails on Windows if dest exists
        manifest[q] = {"url": url, "bytes": dest.stat().st_size, "sha256": sha256(dest),
                       "members": members,
                       "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        manifest_path.write_text(json.dumps(manifest, indent=2))
        new.append(q)
        time.sleep(1.0)                              # stay far below SEC rate limits
    print(f"Manifest: {manifest_path}")
    return new


if __name__ == "__main__":
    main()
