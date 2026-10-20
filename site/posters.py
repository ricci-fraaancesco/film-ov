#!/usr/bin/env python3
"""
Keep a local copy of each poster, so visitors never load images from the cinemas' CDN.

    python site/posters.py --csv data/ov_showtimes.csv --data data --cache .cache/posters --out public/posters

- A poster URL never changes (it contains a unique id), so each one is downloaded
  ONCE, ever, and kept in the cache folder (restored between runs by GitHub Actions).
- Two WebP sizes are made: small (thumbnails, 120 px wide) and medium (cards and film
  page, up to 480 px wide).
- Only the posters of films listed tonight are copied to the site. If a cinema removes
  a poster, it disappears from the site with the next update.
- If a download fails, the site falls back to the cinema's own URL for that poster.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
import time
from pathlib import Path

USER_AGENT = "FilmOV-bot/0.1 (+https://github.com/ricci-fraaancesco/film-ov; one download per poster)"
SIZES = {"s": 120, "m": 480}
DELAY_S = 1.0
MAX_DOWNLOADS = 200  # per run, to stay gentle even if many films are new


def poster_name(url: str) -> str:
    """Stable file stem for a poster URL (the same function is used by build_data.py)."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def make_sizes(raw: bytes, stem: str, folder: Path) -> None:
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        for key, width in SIZES.items():
            w = min(width, im.width)
            h = round(im.height * w / im.width)
            im.resize((w, h), Image.LANCZOS).save(folder / f"{stem}-{key}.webp", "WEBP", quality=80, method=6)


def http_get(url: str) -> bytes:
    import requests

    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.content


def wanted_posters(csv_path: Path, data_dir: Path) -> set[str]:
    try:
        pages = json.loads((data_dir / "film_pages.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        pages = {}
    urls = set()
    with open(csv_path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            u = pages.get(r.get("film_url", ""), {}).get("poster") or r.get("poster", "")
            if u.startswith("http"):
                urls.add(u)
    return urls


def sync(urls: set[str], cache: Path, out: Path, fetch=http_get, delay: float = DELAY_S) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    if out.exists():
        shutil.rmtree(out)  # publish only tonight's posters
    out.mkdir(parents=True)
    stats = {"wanted": len(urls), "downloaded": 0, "cached": 0, "failed": 0}
    for url in sorted(urls):
        stem = poster_name(url)
        have = all((cache / f"{stem}-{k}.webp").exists() for k in SIZES)
        if not have:
            if stats["downloaded"] >= MAX_DOWNLOADS:
                stats["failed"] += 1
                continue
            try:
                make_sizes(fetch(url), stem, cache)
                stats["downloaded"] += 1
                time.sleep(delay)
            except Exception as e:  # keep going, the site uses the original URL for this one
                print(f"  poster {url}: ERROR {e}", file=sys.stderr)
                stats["failed"] += 1
                continue
        else:
            stats["cached"] += 1
        for k in SIZES:
            shutil.copy2(cache / f"{stem}-{k}.webp", out / f"{stem}-{k}.webp")
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/ov_showtimes.csv"))
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--cache", type=Path, default=Path(".cache/posters"))
    ap.add_argument("--out", type=Path, default=Path("public/posters"))
    a = ap.parse_args(argv)
    stats = sync(wanted_posters(a.csv, a.data), a.cache, a.out)
    print(f"Posters: {stats['wanted']} in use, {stats['downloaded']} downloaded tonight, "
          f"{stats['cached']} from cache, {stats['failed']} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
