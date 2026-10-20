#!/usr/bin/env python3
"""
Match the film titles found at the cinemas with Wikidata films.

    python site/wikidata_match.py --csv data/ov_showtimes.csv --data data

Why Wikidata: its data is CC0 (public domain), so it can be used on a commercial site
without a licence. From each match we keep the Italian and original title, year,
original language, director, runtime, the IMDb/TMDB ids (for the future) and the
first sentence of the Italian Wikipedia article (CC BY-SA, credited on the site).

How it decides:
- searches Wikidata for each title variant (full title, the part in brackets, the
  two halves of "A - B"), only among items that are films
- scores each candidate on title similarity (Italian, English and original titles),
  then uses the director and year from the cinema's film page as evidence
- confidence 'high' = safe to merge; 'medium' = used, but listed in data/film_review.md

Files in data/:
- film_matches.json     cache, one entry per title. Titles with no match are retried after a week.
- film_overrides.json   manual fixes: {"POSSIBLE LOVE": "Q12345678", "MARATONA HALLOWEEN": null}
- film_review.md        medium-confidence matches and titles with no match
- film_pages.json       (written by the scraper) synopsis, year, director from the cinema
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from films import film_key, norm, query_variants  # noqa: E402

WD_API = "https://www.wikidata.org/w/api.php"
WP_SUMMARY = "https://it.wikipedia.org/api/rest_v1/page/summary/"
USER_AGENT = "FilmOV/0.1 (https://github.com/ricci-fraaancesco/film-ov; film listings bot)"
# instance of: film, documentary film, animated film, short film, television film, concert film
FILM_CLASSES = ["Q11424", "Q93204", "Q202866", "Q24862", "Q506240", "Q1268687"]
RETRY_DAYS = 7
ACCEPT = 0.82
HIGH = 0.95


# ---------------------------------------------------------------- scoring (pure functions, tested)
def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def title_score(names: list[str], variants: list[str]) -> float:
    """Best similarity between a variant of the cinema title and any title of the candidate.
    Partial variants weigh a bit less, so 'HAPPINESS - FELICITA'' prefers the film whose
    full Italian title is 'Happiness - Felicità' over a film called just 'Felicità'."""
    best = 0.0
    for i, v in enumerate(variants):
        w = 1.0 if i == 0 else 0.97
        for n in names:
            if n:
                best = max(best, similarity(v, n) * w)
    return best


def same_person(a: str, b: str) -> bool:
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    # same surname and same first initial: "A. G. Inarritu" vs "Alejandro Gonzalez Inarritu"
    return ta[-1] == tb[-1] and ta[0][0] == tb[0][0]


def evidence(cand: dict, hint: dict) -> tuple[float, bool]:
    """Score adjustment from the cinema's director and year. Returns (delta, director_matched)."""
    delta, dmatch = 0.0, False
    hd = [d.strip() for d in re.split(r",| e | and ", hint.get("director") or "") if d.strip()]
    if hd and cand.get("directors"):
        if any(same_person(h, d) for h in hd for d in cand["directors"]):
            delta += 0.10
            dmatch = True
        else:
            delta -= 0.15
    hy, cy = hint.get("year"), cand.get("year")
    if hy and cy:
        diff = abs(int(hy) - int(cy))
        if diff <= 1:
            delta += 0.05
        elif diff > 3 and not dmatch:
            delta -= 0.05  # small: cinemas sometimes give the year of a restoration
    return delta, dmatch


def choose(cands: list[dict], variants: list[str], hint: dict) -> tuple[dict | None, str, float]:
    scored = []
    for c in cands:
        base = title_score(c["names"], variants)
        if base < ACCEPT:
            continue
        delta, dmatch = evidence(c, hint)
        scored.append((round(base + delta, 3), dmatch, c.get("sitelinks", 0), c))
    if not scored:
        return None, "none", 0.0
    scored.sort(key=lambda x: (x[0], x[2]), reverse=True)
    s, dmatch, links, best = scored[0]
    if s < ACCEPT:
        return None, "none", s
    if s < HIGH:
        return best, "medium", s
    rivals = [x for x in scored[1:] if x[0] >= HIGH]
    if not rivals or dmatch or links >= 3 * max(r[2] for r in rivals):
        return best, "high", s
    return best, "medium", s


def first_sentence(text: str, min_len: int = 40) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    m = re.search(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý«\"])", text[min_len:])
    return text[: min_len + m.start()].strip() if m else text


# ---------------------------------------------------------------- Wikidata client
class Wikidata:
    def __init__(self):
        import requests

        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.calls = 0
        self.labels: dict[str, str] = {}

    def _get(self, url: str, **params) -> dict:
        for attempt in range(4):
            r = self.s.get(url, params=params or None, timeout=30)
            self.calls += 1
            if r.status_code in (429, 503) or (r.headers.get("content-type", "").startswith("application/json") and "maxlag" in r.text[:200]):
                time.sleep(int(r.headers.get("Retry-After", 5)) + attempt * 3)
                continue
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            time.sleep(0.2)
            return r.json()
        r.raise_for_status()
        return {}

    def search_films(self, query: str, limit: int = 8) -> list[str]:
        q = re.sub(r'["]', " ", query)
        classes = "|".join(f"P31={c}" for c in FILM_CLASSES)
        d = self._get(WD_API, action="query", list="search", format="json", srlimit=limit,
                      srsearch=f"{q} haswbstatement:{classes}", maxlag=5)
        return [h["title"] for h in d.get("query", {}).get("search", [])]

    def entities(self, ids: list[str], props: str, langs: str = "it|en") -> dict:
        out = {}
        for i in range(0, len(ids), 40):
            d = self._get(WD_API, action="wbgetentities", format="json", ids="|".join(ids[i:i + 40]),
                          props=props, languages=langs, languagefallback=1, maxlag=5)
            out.update(d.get("entities", {}))
        return out

    def label(self, ids: list[str]) -> None:
        need = [i for i in set(ids) if i not in self.labels]
        for qid, e in self.entities(need, "labels", "it|en|mul").items():
            lab = e.get("labels", {})
            self.labels[qid] = (lab.get("it") or lab.get("en") or lab.get("mul") or {}).get("value", qid)

    def intro(self, itwiki_title: str) -> str:
        d = self._get(WP_SUMMARY + quote(itwiki_title.replace(" ", "_"), safe=""))
        return first_sentence(d.get("extract", "")) if d.get("type") == "standard" else ""


def _claims(e: dict, prop: str) -> list:
    out = []
    for c in e.get("claims", {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if v is not None and c.get("rank") != "deprecated":
            out.append(v)
    return out


def candidate_from(qid: str, e: dict) -> dict:
    labels = e.get("labels", {})
    it = labels.get("it", {}).get("value", "")
    en = labels.get("en", {}).get("value", "")
    orig = [v["text"] for v in _claims(e, "P1476") if isinstance(v, dict) and v.get("text")]
    years = []
    for v in _claims(e, "P577"):
        m = re.match(r"^\+?(\d{4})", v.get("time", "")) if isinstance(v, dict) else None
        if m:
            years.append(int(m.group(1)))
    dur = None
    for v in _claims(e, "P2047"):
        try:
            dur = round(float(v["amount"]))
            if v.get("unit", "").endswith("Q7727"):
                break  # minutes
            if v.get("unit", "").endswith("Q11574"):
                dur = round(dur / 60)  # seconds
        except (KeyError, ValueError, TypeError):
            pass
    first = lambda p: next((v for v in _claims(e, p) if isinstance(v, str)), None)
    return {
        "qid": qid,
        "names": [n for n in [it, en, *orig] if n],
        "title_it": it or en or (orig[0] if orig else qid),
        "original_title": orig[0] if orig else "",
        "year": min(years) if years else None,
        "director_ids": [v["id"] for v in _claims(e, "P57") if isinstance(v, dict) and "id" in v],
        "language_ids": [v["id"] for v in _claims(e, "P364") if isinstance(v, dict) and "id" in v],
        "runtime": dur,
        "imdb": first("P345"),
        "tmdb": first("P4947"),
        "itwiki": e.get("sitelinks", {}).get("itwiki", {}).get("title"),
        "sitelinks": len(e.get("sitelinks", {})),
    }


def match_title(wd: Wikidata, title: str, hint: dict) -> dict:
    variants = query_variants(title)
    pool: dict[str, dict] = {}
    best = (None, "none", 0.0)
    for q in variants[:3]:
        ids = [i for i in wd.search_films(q) if i not in pool]
        if ids:
            for qid, e in wd.entities(ids, "labels|claims|sitelinks").items():
                if "missing" not in e:
                    pool[qid] = candidate_from(qid, e)
            wd.label([d for c in pool.values() for d in c["director_ids"]])
            for c in pool.values():
                c["directors"] = [wd.labels.get(d, "") for d in c["director_ids"]]
        best = choose(list(pool.values()), variants, hint)
        if best[1] == "high":
            break
    cand, conf, score = best
    today = date.today().isoformat()
    if not cand:
        return {"qid": None, "checked": today, "query": variants[0]}
    wd.label(cand["language_ids"])
    rec = {k: cand[k] for k in ("qid", "title_it", "original_title", "year", "runtime", "imdb", "tmdb", "itwiki")}
    rec["directors"] = cand.get("directors", [])
    rec["languages"] = [wd.labels.get(l, "") for l in cand["language_ids"]]
    rec["intro"] = wd.intro(cand["itwiki"]) if cand.get("itwiki") else ""
    rec.update({"confidence": conf, "score": score, "query": variants[0], "source": "search", "checked": today})
    return rec


def record_for_qid(wd: Wikidata, qid: str, title: str) -> dict:
    e = wd.entities([qid], "labels|claims|sitelinks").get(qid, {})
    if not e or "missing" in e:
        return {"qid": None, "source": "override", "checked": date.today().isoformat(), "error": f"{qid} not found"}
    c = candidate_from(qid, e)
    wd.label(c["director_ids"] + c["language_ids"])
    rec = {k: c[k] for k in ("qid", "title_it", "original_title", "year", "runtime", "imdb", "tmdb", "itwiki")}
    rec["directors"] = [wd.labels.get(d, "") for d in c["director_ids"]]
    rec["languages"] = [wd.labels.get(l, "") for l in c["language_ids"]]
    rec["intro"] = wd.intro(c["itwiki"]) if c.get("itwiki") else ""
    rec.update({"confidence": "high", "score": 1.0, "query": title, "source": "override", "checked": date.today().isoformat()})
    return rec


# ---------------------------------------------------------------- main
def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def hints_from(rows: list[dict], pages: dict) -> dict[str, dict]:
    """Director and year per film key, from the scraper (homepage + film page)."""
    hints: dict[str, dict] = {}
    for r in rows:
        k = film_key(r["title"])
        h = hints.setdefault(k, {"director": "", "year": None})
        p = pages.get(r.get("film_url", ""), {})
        h["director"] = h["director"] or r.get("director", "") or p.get("director", "")
        h["year"] = h["year"] or p.get("year")
    return hints


def write_review(cache: dict, titles: dict[str, str], path: Path) -> str:
    med = sorted((titles[k], v) for k, v in cache.items() if k in titles and v.get("qid") and v.get("confidence") == "medium")
    none = sorted(titles[k] for k, v in cache.items() if k in titles and not v.get("qid") and v.get("source") != "override")
    lines = ["# Film matches to check", "",
             "Fix a match in `data/film_overrides.json`: the cinema title as key, the Wikidata id",
             "(Q-number, from the wikidata.org/wiki/Q... link) as value, or null if it is not a film.", "",
             "## Medium confidence", ""]
    lines += [f"- {t} -> [{v['title_it']} ({v.get('year') or '?'}, {', '.join(v.get('directors') or []) or 'regista ?'})]"
              f"(https://www.wikidata.org/wiki/{v['qid']})" for t, v in med] or ["- none"]
    lines += ["", "## No match", ""] + ([f"- {t}" for t in none] or ["- none"])
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/ov_showtimes.csv"))
    ap.add_argument("--data", type=Path, default=Path("data"))
    a = ap.parse_args(argv)

    cache_p, over_p = a.data / "film_matches.json", a.data / "film_overrides.json"
    cache = load_json(cache_p, {})
    overrides = {film_key(k): v for k, v in load_json(over_p, {}).items() if not k.startswith("_")}
    with open(a.csv, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    titles: dict[str, str] = {}
    for r in rows:
        titles.setdefault(film_key(r["title"]), r["title"])
    hints = hints_from(rows, load_json(a.data / "film_pages.json", {}))

    wd = Wikidata()
    today = date.today()
    looked = 0
    for key, title in sorted(titles.items()):
        try:
            cur = cache.get(key)
            if key in overrides:
                oid = overrides[key]
                if oid is None:
                    if not (cur and cur.get("source") == "override" and cur.get("qid") is None):
                        cache[key] = {"qid": None, "source": "override", "checked": today.isoformat()}
                elif not (cur and cur.get("source") == "override" and cur.get("qid") == oid):
                    cache[key] = record_for_qid(wd, oid, title)
                continue
            stale_none = cur and not cur.get("qid") and today - date.fromisoformat(cur["checked"]) >= timedelta(days=RETRY_DAYS)
            if cur is None or stale_none or (cur.get("source") == "override"):
                cache[key] = match_title(wd, title, hints.get(key, {}))
                looked += 1
                m = cache[key]
                print(f"  {title!r} -> {m.get('title_it')} ({m.get('year')}, {', '.join(m.get('directors') or [])}) [{m.get('confidence', 'none')}]")
        except Exception as e:  # one bad title must not stop the run
            print(f"  {title!r}: ERROR {e}", file=sys.stderr)

    cache_p.write_text(json.dumps(dict(sorted(cache.items())), indent=1, ensure_ascii=False), encoding="utf-8")
    if not over_p.exists():
        over_p.write_text(json.dumps({"_help": "cinema title -> Wikidata Q-id, or null if it is not a film"}, indent=1) + "\n", encoding="utf-8")
    review = write_review(cache, titles, a.data / "film_review.md")
    matched = sum(1 for k in titles if cache.get(k, {}).get("qid"))
    summary = f"Wikidata: {matched}/{len(titles)} titles matched, {looked} looked up in this run, {wd.calls} requests."
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(summary + "\n\n" + review)
    return 0


if __name__ == "__main__":
    sys.exit(main())
