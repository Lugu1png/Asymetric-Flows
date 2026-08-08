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


def sha256(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(block), b""):
            h.update(b)
    return h.hexdigest()


def main():
    if not C.USER_AGENT or "@" not in C.USER_AGENT:
        raise SystemExit("Set SEC_USER_AGENT to 'Name email@domain' (SEC fair-access policy).")
    C.RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = C.RAW / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    s = requests.Session()
    s.headers.update({"User-Agent": C.USER_AGENT, "Accept-Encoding": "gzip, deflate"})

    for q in C.quarters():
        dest = C.RAW / f"{q}_nport.zip"
        if dest.exists() and q in manifest and manifest[q]["sha256"] == sha256(dest):
            print(f"{q}: present, checksum ok")
            continue
        url = C.BASE_URL.format(q=q)
        print(f"{q}: downloading {url}")
        tmp = dest.with_suffix(".part")
        with s.get(url, stream=True, timeout=120) as r:
            if r.status_code == 404:
                print(f"{q}: not published (404), skipping")
                continue
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        with zipfile.ZipFile(tmp) as zf:            # fails loudly on a truncated file
            members = zf.namelist()
        tmp.rename(dest)
        manifest[q] = {"url": url, "bytes": dest.stat().st_size, "sha256": sha256(dest),
                       "members": members,
                       "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        manifest_path.write_text(json.dumps(manifest, indent=2))
        time.sleep(1.0)                              # stay far below SEC rate limits
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
