#!/usr/bin/env python3
"""
Match the film titles found at the cinemas with TMDB movies.

    TMDB_TOKEN=... python site/tmdb_match.py --csv data/ov_showtimes.csv --data data

- Only titles not yet in data/tmdb_cache.json are looked up, so a normal night makes
  a handful of requests. Titles with no match are retried after RETRY_DAYS (new films
  often appear on TMDB later).
- data/tmdb_overrides.json fixes wrong matches by hand. Keys are the title as the
  cinema writes it (any case), values are a TMDB movie id or null for "not a film":
      {"POSSIBLE LOVE": 1234567, "MARATONA HALLOWEEN: CREATURE A SORPRESA": null}
- data/tmdb_review.md lists matches worth a look (medium confidence, no match).
- Without TMDB_TOKEN the script prints a warning and exits 0, so the site still builds.

TMDB_TOKEN can be the v4 "API Read Access Token" (starts with eyJ) or the v3 API key.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from films import film_key, norm, query_variants  # noqa: E402

API = "https://api.themoviedb.org/3"
RETRY_DAYS = 7
ACCEPT = 0.82        # minimum title similarity to accept a result
HIGH = 0.95          # similarity for a confident match
USER_AGENT = "FilmOV/0.1 (+https://github.com/ricci-fraaancesco/film-ov)"


# ---------------------------------------------------------------- scoring
def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def title_score(result: dict, variants: list[str]) -> float:
    """Best similarity between any variant and the TMDB title or original title.
    Partial variants (one half of 'A - B' or 'A (B)') weigh a bit less than the full
    title, so 'HAPPINESS - FELICITA'' prefers 'Happiness - Felicità' over 'Felicità'."""
    names = [result.get("title") or "", result.get("original_title") or ""]
    best = 0.0
    for i, v in enumerate(variants):
        w = 1.0 if i == 0 else 0.97
        for n in names:
            best = max(best, similarity(v, n) * w)
    return best


def choose(results: list[dict], variants: list[str]) -> tuple[dict | None, str, float]:
    """Pick the best TMDB result. Returns (result, confidence, similarity).
    confidence: 'high', 'medium' or 'none'."""
    scored = []
    for r in results:
        s = title_score(r, variants)
        if s >= ACCEPT:
            scored.append((round(s, 2), r.get("popularity") or 0.0, r))
    if not scored:
        return None, "none", 0.0
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best_s, best_pop, best = scored[0]
    if best_s < HIGH:
        return best, "medium", best_s
    # several films with the same title (remakes): confident only if one is much better known
    rivals = [p for s, p, _ in scored[1:] if s >= HIGH]
    if rivals and best_pop < 3 * max(rivals):
        return best, "medium", best_s
    return best, "high", best_s


# ---------------------------------------------------------------- TMDB client
class Tmdb:
    def __init__(self, token: str):
        import requests

        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.params = {}
        if token.startswith("eyJ"):
            self.s.headers["Authorization"] = f"Bearer {token}"
        else:
            self.params["api_key"] = token
        self.calls = 0

    def get(self, path: str, **params) -> dict:
        for attempt in range(3):
            r = self.s.get(API + path, params={**self.params, **params}, timeout=20)
            self.calls += 1
            if r.status_code == 429:
                time.sleep(2 + attempt * 3)
                continue
            r.raise_for_status()
            time.sleep(0.25)
            return r.json()
        r.raise_for_status()
        return {}

    def search(self, query: str) -> list[dict]:
        return self.get("/search/movie", query=query, language="it-IT", include_adult="false").get("results", [])

    def movie(self, movie_id: int) -> dict:
        return self.get(f"/movie/{movie_id}", language="it-IT")

    def overview_en(self, movie_id: int) -> str:
        return self.get(f"/movie/{movie_id}", language="en-US").get("overview", "")


def record_from(movie: dict, confidence: str, sim: float, query: str, source: str) -> dict:
    year = (movie.get("release_date") or "")[:4]
    return {
        "id": movie["id"],
        "title": movie.get("title") or movie.get("original_title"),
        "original_title": movie.get("original_title"),
        "original_language": movie.get("original_language"),
        "year": int(year) if year.isdigit() else None,
        "poster_path": movie.get("poster_path"),
        "overview": (movie.get("overview") or "").strip(),
        "runtime": movie.get("runtime"),
        "confidence": confidence,
        "similarity": sim,
        "query": query,
        "source": source,
        "checked": date.today().isoformat(),
    }


def match_title(api: Tmdb, title: str) -> dict:
    variants = query_variants(title)
    pool: dict[int, dict] = {}
    best = (None, "none", 0.0)
    for q in variants[:3]:
        for r in api.search(q):
            pool.setdefault(r["id"], r)
        best = choose(list(pool.values()), variants)
        if best[1] == "high":
            break
    movie, conf, sim = best
    if not movie:
        return {"id": None, "checked": date.today().isoformat(), "query": variants[0]}
    full = api.movie(movie["id"])  # adds runtime, and the Italian title/overview
    if not full.get("overview"):
        full["overview"] = api.overview_en(movie["id"])
    return record_from(full, conf, sim, variants[0], "search")


# ---------------------------------------------------------------- main
def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def needs_lookup(entry: dict | None, today: date) -> bool:
    if entry is None:
        return True
    if entry.get("id") is None and entry.get("source") != "override":
        checked = date.fromisoformat(entry.get("checked", "2000-01-01"))
        return today - checked >= timedelta(days=RETRY_DAYS)
    return False


def write_review(cache: dict, titles: dict[str, str], path: Path) -> str:
    med = [(k, v) for k, v in cache.items() if k in titles and v.get("id") and v.get("confidence") == "medium"]
    none = [k for k, v in cache.items() if k in titles and not v.get("id") and v.get("source") != "override"]
    lines = ["# TMDB matches to check", "",
             "Fix a wrong match in `data/tmdb_overrides.json`: the cinema title as key, the TMDB id as value",
             "(the number in the themoviedb.org/movie/<id> link), or null if it is not a film.", ""]
    lines += ["## Medium confidence", ""]
    lines += [f"- {titles[k]} -> [{v['title']} ({v.get('year') or '?'})](https://www.themoviedb.org/movie/{v['id']})" for k, v in sorted(med)] or ["- none"]
    lines += ["", "## No match", ""]
    lines += [f"- {titles[k]}" for k in sorted(none)] or ["- none"]
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/ov_showtimes.csv"))
    ap.add_argument("--data", type=Path, default=Path("data"))
    a = ap.parse_args(argv)

    cache_p, over_p = a.data / "tmdb_cache.json", a.data / "tmdb_overrides.json"
    cache = load_json(cache_p, {})
    overrides = {film_key(k): v for k, v in load_json(over_p, {}).items() if not k.startswith("_")}
    titles: dict[str, str] = {}
    with open(a.csv, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            titles.setdefault(film_key(r["title"]), r["title"])

    token = os.environ.get("TMDB_TOKEN", "").strip()
    if not token:
        print("TMDB_TOKEN not set: skipping TMDB matching, the site will use the cinema titles.")
        return 0
    api = Tmdb(token)
    today = date.today()
    new = 0
    for key, title in sorted(titles.items()):
        try:
            if key in overrides:
                oid = overrides[key]
                cur = cache.get(key, {})
                if oid is None and not (cur.get("source") == "override" and cur.get("id") is None):
                    cache[key] = {"id": None, "source": "override", "checked": today.isoformat()}
                elif oid is not None and not (cur.get("source") == "override" and cur.get("id") == oid):
                    cache[key] = record_from(api.movie(int(oid)), "high", 1.0, title, "override")
                continue
            if needs_lookup(cache.get(key), today):
                cache[key] = match_title(api, title)
                new += 1
                m = cache[key]
                print(f"  {title!r} -> {m.get('title')} ({m.get('year')}) [{m.get('confidence', 'none')}]")
        except Exception as e:  # one bad title must not stop the run
            print(f"  {title!r}: ERROR {e}", file=sys.stderr)

    cache_p.write_text(json.dumps(dict(sorted(cache.items())), indent=1, ensure_ascii=False), encoding="utf-8")
    if not over_p.exists():
        over_p.write_text(json.dumps({"_help": "cinema title -> TMDB id, or null if it is not a film"}, indent=1) + "\n", encoding="utf-8")
    review = write_review(cache, titles, a.data / "tmdb_review.md")
    matched = sum(1 for k in titles if cache.get(k, {}).get("id"))
    summary = f"TMDB: {matched}/{len(titles)} titles matched, {new} looked up tonight, {api.calls} API calls."
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(summary + "\n\n" + review)
    return 0


if __name__ == "__main__":
    sys.exit(main())
