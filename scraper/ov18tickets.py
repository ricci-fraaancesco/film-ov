#!/usr/bin/env python3
"""
ov18tickets: pulls original-version (OV) showtimes from 18tickets storefronts.

18tickets (by 18Months) is the ticketing platform used by about half of the
OV venues in Rome and Bologna. All storefronts share one HTML template:

  <h6><a class="movie__title" href="/film/{film_id}">TITLE</a></h6>
  ...block = h6.parent.parent...
     <span class="film-label">V.O.S.</span>
     <p class="movie__option"><strong>Language:</strong> Inglese con sottotitoli</p>
     <a data-time="{epoch_ms}" href="https://{venue}.{storefront}/film/{id}/{uuid}#theater-init">
        <li>21:00 Sala 1 [label]</li>
     </a>

The cinema is taken from the booking URL subdomain, never from the screen name
(e.g. "Scorsese" and "Mastroianni" are screens of Cinema Lumiere).

Usage
  python ov18tickets.py live   --out data/          # fetch from the web (nightly job)
  python ov18tickets.py replay --raw raw/ --out data/  # rebuild from rows captured in a browser

Outputs
  ov_showtimes.csv   one row per OV screening, with a direct booking link
  run_stats.json     shows per venue, used for monitoring
  alerts.txt         venues whose show count dropped to zero (template change, blocked, closed)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
sys.path.insert(0, str(Path(__file__).parent))  # webtic.py, uci.py, langs.py live next to this file
USER_AGENT = "FilmOV-bot/0.1 (+mailto:rcc.francesco@gmail.com; OV listings, 1 request/5s)"
REQUEST_DELAY_S = 5

# --------------------------------------------------------------------------
# Venue registry. Key = storefront host. Value = {subdomain: (cinema, city)}.
# "pages" lists the URLs to fetch: most storefronts list every venue on the
# root page; cdr needs one page per venue.
# --------------------------------------------------------------------------
STOREFRONTS: dict[str, dict] = {
    "ccb.18tickets.it": {
        "pages": ["https://ccb.18tickets.it/"],
        "venues": {
            "odeon": ("Cinema Odeon", "Bologna"),
            "europa": ("Europa Cinema", "Bologna"),
            "rialto": ("Rialto Studios", "Bologna"),
            "roma": ("Roma d'Essai", "Bologna"),
        },
    },
    "cinetecabologna.18tickets.it": {
        "pages": ["https://cinetecabologna.18tickets.it/"],
        "venues": {
            "lumiere": ("Cinema Lumière", "Bologna"),
            "modernissimo": ("Cinema Modernissimo", "Bologna"),
            "cervi": ("Sala Cervi", "Bologna"),
        },
    },
    "popupcinema.18tickets.it": {
        "pages": ["https://popupcinema.18tickets.it/"],
        "venues": {
            "arlecchino": ("Pop Up Cinema Arlecchino", "Bologna"),
            "jolly": ("Pop Up Cinema Jolly", "Bologna"),
            "medica": ("Pop Up Cinema Medica", "Bologna"),
            "bristol": ("Pop Up Cinema Bristol", "Bologna"),
        },
    },
    "ccroma.18tickets.it": {
        "pages": ["https://ccroma.18tickets.it/"],
        "venues": {
            "quattrofontane": ("Quattro Fontane", "Roma"),
            "giuliocesare": ("Giulio Cesare", "Roma"),
            "nuovoolimpia": ("Nuovo Olimpia", "Roma"),
            "eurcine": ("Eurcine", "Roma"),
            "fossolo": ("Cinema Fossolo", "Bologna"),
            # same storefront, outside the MVP cities (kept, free coverage)
            "flora": ("Cinema Flora", "Firenze"),
            "fiorella": ("Cinema Fiorella", "Firenze"),
            "metropolitan": ("Cinema Metropolitan", "Napoli"),
        },
    },
    "cdr.18tickets.it": {
        "pages": [
            "https://lux.cdr.18tickets.it/",
            "https://odeon.cdr.18tickets.it/",
            "https://intrastevere.cdr.18tickets.it/",
            "https://tibur.cdr.18tickets.it/",
        ],
        "venues": {
            "lux": ("Multisala Lux", "Roma"),
            "odeon": ("Odeon Multiscreen", "Roma"),
            "intrastevere": ("Cinema Intrastevere", "Roma"),
            "tibur": ("Cinema Tibur", "Roma"),
        },
    },
    "barberini.18tickets.it": {
        "pages": ["https://cinema.barberini.18tickets.it/"],
        "venues": {
            "cinema": ("Multisala Barberini", "Roma"),
        },
    },
    # TODO: Troisi (18tickets, storefront to confirm). Greenwich uses its own site
    # (multisalagreenwichroma.com), so it needs a separate adapter.
}

# --------------------------------------------------------------------------
# OV detection. Order matters: an explicit "dubbed" wins over everything.
# --------------------------------------------------------------------------
RE_DUBBED = re.compile(r"doppiag|doppiat", re.I)
RE_SILENT = re.compile(r"^\s*muto\s*$", re.I)
RE_OV_TITLE = re.compile(
    r"(^|[\s\-\(])v\.\s?o\.?(\s?s\.?)?($|[\s\)])"
    r"|original\s?(language|version)|lingua originale|versione originale|\bvos\b",
    re.I,
)
RE_OV_LANG = re.compile(r"sottotitol|originale|subtit", re.I)

# Suffixes/prefixes the venues add to titles to flag OV. Stripped for display
# and for matching the same film across venues.
RE_TITLE_NOISE = [
    re.compile(r"^\s*original version\s*:\s*", re.I),
    re.compile(r"\s*[-–]\s*(original (language|version)|v\.\s?o\.?\s?s?\.?)\s*$", re.I),
    re.compile(r"\s*\((v\.\s?o\.?\s?s?\.?|vos|original language)\)\s*$", re.I),
]


def is_ov(title: str, label: str, language: str) -> tuple[bool, str]:
    """Return (is_ov, reason). Reason is kept in the CSV for auditing."""
    t = f"{title} {label}"
    lang = language.strip()
    if RE_DUBBED.search(lang):
        return False, "dubbed"
    if RE_SILENT.match(lang):
        return False, "silent film"
    if RE_OV_TITLE.search(t):
        return True, "title/label"
    if RE_OV_LANG.search(lang):
        return True, "language field"
    if lang and not re.search(r"italian", lang, re.I):
        return True, "non-Italian language"
    return False, "no OV signal"


def clean_title(title: str) -> str:
    out = title
    for rx in RE_TITLE_NOISE:
        out = rx.sub("", out)
    out = re.sub(r"\s+", " ", out).strip(" -–")
    return out


# "sottotitolato", "sott.", "sub.", "subtitles", and the V.O.S. abbreviation
_SUB_MARK = re.compile(r"sottotitol\w*|subtitle\w*|\bsott\b\.?|\bsubs?\b\.?|\bv\.?\s?o\.?\s?s\b\.?")
_SUB_IT = re.compile(r"italian|\bita?\b")
_SUB_EN = re.compile(r"ingles|english|\beng?\b")


def _subs_from(text: str) -> str:
    m = _SUB_MARK.search((text or "").lower())
    if not m:
        return ""
    after = text.lower()[m.end():]
    it, en = bool(_SUB_IT.search(after)), bool(_SUB_EN.search(after))
    if it and en:
        return "sub IT+EN"
    if en:
        return "sub EN"
    return "sub IT"  # Italian cinemas: subtitles with no language named are Italian


def subtitle_info(language: str, label: str = "") -> str:
    """'sub IT' / 'sub EN' / 'sub IT+EN', or '' when the cinema doesn't say.
    The language field wins; the cinema's label is the fallback."""
    return _subs_from(language) or _subs_from(label)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Show:
    storefront: str
    venue_sub: str
    cinema: str
    city: str
    film_id: str
    title_raw: str
    title: str
    language: str
    label: str
    starts_at: str        # ISO 8601, Europe/Rome
    date: str
    time: str
    screen: str
    booking_url: str
    is_ov: bool
    ov_reason: str
    subtitles: str = ""
    film_url: str = ""    # the film's page on the storefront (synopsis, year, poster)
    poster: str = ""      # poster image published by the cinema
    director: str = ""


def add_venues_from_list(path: Path) -> int:
    """Add the 18tickets cinemas activated in data/venues.csv (by the website check or by
    hand) to STOREFRONTS. Cinemas configured above keep their settings."""
    import csv as _csv

    if not path or not Path(path).exists():
        return 0
    added = 0
    with open(path, encoding="utf-8") as fh:
        for r in _csv.DictReader(fh):
            if r.get("status") != "active" or r.get("platform") != "18tickets" or not r.get("booking_url"):
                continue
            host = (urlparse_host(r["booking_url"]))
            parts = host.split(".")
            if not host.endswith("18tickets.it") or len(parts) < 3:
                continue
            storefront = ".".join(parts[-3:])
            sub = ".".join(parts[:-3])
            if sub == "main":
                sub = ""
            cfg = STOREFRONTS.setdefault(storefront, {"pages": [], "venues": {}})
            if (sub or "main") in cfg["venues"]:
                continue  # already read for another cinema: never mix two cinemas on one page
            if not sub and cfg["pages"]:
                continue
            cfg["venues"][sub or "main"] = (r["name"], r["city"])
            page = f"https://{host}/"
            root = f"https://{storefront}/"
            if page not in cfg["pages"] and root not in cfg["pages"]:
                cfg["pages"].append(page)
            added += 1
    return added


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def venue_for(storefront: str, sub: str) -> tuple[str, str]:
    venues = STOREFRONTS.get(storefront, {}).get("venues", {})
    return venues.get(sub, (sub.title(), "?"))


def make_show(storefront, sub, film_id, title, language, label, epoch_s, screen, uuid,
              film_url="", poster="", director="") -> Show:
    cinema, city = venue_for(storefront, sub)
    dt = datetime.fromtimestamp(float(epoch_s), tz=timezone.utc).astimezone(ROME)
    ov, reason = is_ov(title, label, language)
    return Show(
        storefront=storefront,
        venue_sub=sub,
        cinema=cinema,
        city=city,
        film_id=str(film_id),
        title_raw=title,
        title=clean_title(title),
        language=language,
        label=label,
        starts_at=dt.isoformat(),
        date=dt.strftime("%Y-%m-%d"),
        time=dt.strftime("%H:%M"),
        screen=screen,
        booking_url=f"https://{sub}.{storefront}/film/{film_id}/{uuid}#theater-init",
        is_ov=ov,
        ov_reason=reason,
        subtitles=subtitle_info(language, label),
        film_url=film_url or f"https://{storefront}/film/{film_id}",
        poster=poster,
        director=director,
    )


# --------------------------------------------------------------------------
# HTML parsing (live mode)
# --------------------------------------------------------------------------
def parse_storefront_html(html: str, storefront: str, page_url: str = "") -> list[Show]:
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, urljoin

    soup = BeautifulSoup(html, "html.parser")
    txt = lambda el: re.sub(r"\s+", " ", el.get_text(" ")).strip() if el else ""
    shows: dict[str, Show] = {}

    for a in soup.select("h6 a.movie__title"):
        m = re.search(r"/film/(\d+)", a.get("href", ""))
        if not m:
            continue
        film_id = m.group(1)
        h6 = a.find_parent("h6")
        block = h6.parent.parent if h6 and h6.parent and h6.parent.parent else h6
        title = txt(a)
        label = txt(block.select_one(".film-label"))
        opts = {}
        for p in block.select("p.movie__option"):
            strong = p.find("strong")
            key = txt(strong).rstrip(":")
            opts[key] = txt(p).replace(txt(strong), "", 1).strip()
        language = opts.get("Language") or opts.get("Lingua") or ""
        director = opts.get("Director") or opts.get("Regia") or ""
        base = page_url or f"https://{storefront}/"
        film_url = urljoin(base, a.get("href", ""))
        img = block.select_one(".movie__images img") or block.find("img")
        poster = urljoin(base, img.get("src") or img.get("data-src") or "") if img else ""

        for s in block.select("a[data-time]"):
            href = s.get("href", "")
            u = urlparse(href)
            if not u.netloc.endswith(storefront):
                continue
            sub = u.netloc[: -len(storefront)].rstrip(".") or "main"
            uuid = u.path.rstrip("/").split("/")[-1]
            li_text = txt(s.find("li"))
            screen = re.sub(r"^\d\d:\d\d\s*", "", li_text)
            epoch_s = int(s["data-time"]) / 1000
            # dedupe: the same screening appears in several homepage sections
            key = f"{sub}|{film_id}|{uuid}"
            if key not in shows:
                shows[key] = make_show(storefront, sub, film_id, title, language, label, epoch_s, screen, uuid,
                                       film_url, poster, director)
    return list(shows.values())


# --------------------------------------------------------------------------
# Film pages: synopsis, year, genre, director, poster. One request per film,
# cached in data/film_pages.json and refreshed after FILM_PAGE_MAX_AGE days.
# --------------------------------------------------------------------------
FILM_PAGE_MAX_AGE = 30
FILM_PAGES_PER_RUN = 150


def parse_film_page(html: str, url: str = "") -> dict:
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "html.parser")
    txt = lambda el: re.sub(r"\s+", " ", el.get_text(" ")).strip() if el else ""
    meta = lambda prop: (soup.find("meta", attrs={"property": prop}) or {}).get("content", "") or ""
    opts = {}
    for p in soup.select("p.movie__option"):
        strong = p.find("strong")
        key = txt(strong).rstrip(":")
        opts.setdefault(key, txt(p).replace(txt(strong), "", 1).strip())
    synopsis = txt(soup.select_one(".collapse .card-body")) or meta("og:description").strip()
    year = opts.get("Year") or opts.get("Anno") or ""
    poster = meta("og:image")
    if not poster:
        img = soup.select_one(".movie__images img")
        poster = img.get("src", "") if img else ""
    return {
        "synopsis": synopsis,
        "year": int(year) if year.strip().isdigit() else None,
        "director": opts.get("Director") or opts.get("Regia") or "",
        "genre": opts.get("Genre") or opts.get("Genere") or "",
        "poster": urljoin(url, poster) if poster else "",
    }


def fetch_film_pages(shows: list[Show], cache_path: Path, today: datetime | None = None) -> dict:
    today = today or datetime.now(ROME)
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    urls = sorted({s.film_url for s in shows if s.is_ov and s.film_url and "18tickets." in s.film_url})
    todo = []
    for u in urls:
        c = cache.get(u)
        if not c or (today - datetime.fromisoformat(c["checked"])).days >= FILM_PAGE_MAX_AGE:
            todo.append(u)
    for u in todo[:FILM_PAGES_PER_RUN]:
        try:
            info = parse_film_page(fetch(u), u)
            info["checked"] = today.isoformat(timespec="seconds")
            cache[u] = info
        except Exception as e:
            print(f"  film page {u}: ERROR {e}", file=sys.stderr)
        time.sleep(REQUEST_DELAY_S)
    print(f"  film pages: {len(todo[:FILM_PAGES_PER_RUN])} fetched, {len(urls)} in use", file=sys.stderr)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(dict(sorted(cache.items())), indent=1, ensure_ascii=False), encoding="utf-8")
    return cache


def fetch(url: str) -> str:
    import requests

    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"}, timeout=30)
    r.raise_for_status()
    return r.text


def run_live() -> tuple[list[Show], dict]:
    all_shows: list[Show] = []
    errors = {}
    for storefront, cfg in STOREFRONTS.items():
        for page in cfg["pages"]:
            try:
                html = fetch(page)
                got = parse_storefront_html(html, storefront, page)
                all_shows.extend(got)
                print(f"  {page}: {len(got)} shows", file=sys.stderr)
            except Exception as e:  # keep going, monitoring will flag it
                errors[page] = repr(e)
                print(f"  {page}: ERROR {e}", file=sys.stderr)
            time.sleep(REQUEST_DELAY_S)
    return all_shows, errors


# --------------------------------------------------------------------------
# Other platforms: Webtic (cinemas activated in data/venues.csv) and UCI (the whole chain)
# --------------------------------------------------------------------------
PLATFORM_DELAY_S = 2


def json_getter(delay: float = PLATFORM_DELAY_S):
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Language": "it-IT,it;q=0.9"})

    def get_json(url, params=None):
        r = s.get(url, params=params, timeout=60)
        r.raise_for_status()
        time.sleep(delay)
        return r.json()
    return get_json


def webtic_cinemas(venues_path: Path) -> list[dict]:
    import csv as _csv
    from webtic import local_id_from_url

    out = []
    if venues_path and Path(venues_path).exists():
        with open(venues_path, encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                if r.get("platform") == "webtic" and r.get("status") == "active":
                    lid = local_id_from_url(r.get("booking_url", ""))
                    if lid and all(o["lid"] != lid for o in out):
                        out.append({"lid": lid, "name": r["name"], "city": r["city"]})
    return out


# UCI's back end answered 403 to our requests on 21 Oct 2026 and the adapter was turned off.
# On 23 Oct it answered normally again to the same identified bot (FilmOV-bot user agent),
# so it is back on. If UCI refuses again (403/429), the run stops asking UCI for the night.
UCI_ENABLED = True


def run_platforms(venues_path: Path | None, pages_path: Path, get_json=None, uci: bool | None = None) -> tuple[list[Show], dict]:
    import uci as uci_mod
    import webtic

    get_json = get_json or json_getter()
    uci = UCI_ENABLED if uci is None else uci
    shows, errors, pages = [], {}, {}
    for c in webtic_cinemas(venues_path):
        try:
            got, pg, _ = webtic.read_cinema(get_json, c["lid"], c["name"], c["city"])
            shows += got
            pages.update(pg)
            print(f"  webtic {c['lid']} {c['city']} / {c['name']}: {len(got)} shows", file=sys.stderr)
        except Exception as e:
            errors[f"webtic:{c['lid']}"] = repr(e)[:200]
            print(f"  webtic {c['lid']}: ERROR {e}", file=sys.stderr)
    if uci:
        try:
            theatres = uci_mod.theatres(get_json)
        except Exception as e:
            errors["uci:theatres"] = repr(e)[:200]
            theatres = []
        for t in theatres:
            try:
                got, pg = uci_mod.parse_programming(get_json(f"{uci_mod.API}/theatres/{t['slug']}/programming"), t)
                shows += got
                for k, v in pg.items():
                    pages.setdefault(k, v)
                print(f"  uci {t['city']} / {t['name']}: {len(got)} shows, {sum(1 for x in got if x.is_ov)} OV", file=sys.stderr)
            except Exception as e:
                errors[f"uci:{t['slug']}"] = repr(e)[:200]
                print(f"  uci {t['slug']}: ERROR {e}", file=sys.stderr)
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (401, 403, 429):  # UCI refuses us: do not insist tonight
                    errors["uci:stopped"] = f"UCI answered {code}, stopped after {t['slug']}"
                    break
        try:
            cache = json.loads(pages_path.read_text(encoding="utf-8")) if pages_path.exists() else {}
        except json.JSONDecodeError:
            cache = {}
        uci_mod.add_directors(get_json, {k: v for k, v in pages.items() if k.startswith(uci_mod.SITE)}, cache)
    # film details go into the same cache the site build reads (data/film_pages.json)
    if pages:
        try:
            cache = json.loads(pages_path.read_text(encoding="utf-8")) if pages_path.exists() else {}
        except json.JSONDecodeError:
            cache = {}
        now = datetime.now(ROME).isoformat(timespec="seconds")
        for k, v in pages.items():
            cache[k] = {**{x: y for x, y in v.items() if x != "uci_slug"}, "checked": now}
        pages_path.parent.mkdir(parents=True, exist_ok=True)
        pages_path.write_text(json.dumps(dict(sorted(cache.items())), indent=1, ensure_ascii=False), encoding="utf-8")
    return shows, errors


# --------------------------------------------------------------------------
# Replay mode: rows captured in a browser with the same parsing logic (JS).
# File raw_<storefront-prefix>.txt, one row per OV-candidate screening:
#   sub|film_id|title|language|label|epoch_s|screen|uuid
# Titles may contain "|", so fields are taken from both ends.
# --------------------------------------------------------------------------
RAW_PREFIX_TO_STOREFRONT = {s.split(".")[0]: s for s in STOREFRONTS}


def parse_raw_line(line: str, storefront: str) -> Show | None:
    parts = line.rstrip("\n").split("|")
    if len(parts) < 8:
        return None
    sub = parts[0].split(".")[0]
    film_id = parts[1]
    language, label, epoch_s, screen, uuid = parts[-5:]
    title = "|".join(parts[2:-5])
    return make_show(storefront, sub, film_id, title, language, label, epoch_s, screen, uuid)


def run_replay(raw_dir: Path) -> tuple[list[Show], dict]:
    shows = []
    for f in sorted(raw_dir.glob("raw_*.txt")):
        prefix = f.stem.removeprefix("raw_")
        storefront = RAW_PREFIX_TO_STOREFRONT[prefix]
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                s = parse_raw_line(line, storefront)
                if s:
                    shows.append(s)
    return shows, {}


# --------------------------------------------------------------------------
# Output + monitoring
# --------------------------------------------------------------------------
CSV_FIELDS = ["city", "cinema", "date", "time", "title", "language", "subtitles", "screen",
              "label", "booking_url", "film_id", "title_raw", "venue_sub", "storefront",
              "starts_at", "ov_reason", "film_url", "poster", "director"]


def dedupe(shows: list[Show]) -> list[Show]:
    seen, out = set(), []
    for s in shows:
        k = s.booking_url
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def write_outputs(shows: list[Show], errors: dict, out_dir: Path, now: datetime | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(ROME)
    ov = [s for s in dedupe(shows) if s.is_ov and s.starts_at >= now.isoformat()]
    ov.sort(key=lambda s: (s.city, s.cinema, s.starts_at))

    with open(out_dir / "ov_showtimes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for s in ov:
            w.writerow(asdict(s))

    per_venue: dict[str, int] = {}
    for s in ov:
        per_venue[f"{s.city} / {s.cinema}"] = per_venue.get(f"{s.city} / {s.cinema}", 0) + 1

    stats_path = out_dir / "run_stats.json"
    previous = json.loads(stats_path.read_text())["ov_per_venue"] if stats_path.exists() else {}
    alerts = [f"{v}: {n} OV shows last run, 0 now" for v, n in previous.items() if n > 0 and per_venue.get(v, 0) == 0]
    alerts += [f"fetch error {p}: {e}" for p, e in errors.items()]
    (out_dir / "alerts.txt").write_text("\n".join(alerts) + ("\n" if alerts else ""), encoding="utf-8")

    stats = {"run_at": now.isoformat(), "ov_shows": len(ov), "ov_per_venue": per_venue, "errors": errors}
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["live", "replay"])
    ap.add_argument("--raw", type=Path, default=Path("raw"))
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--now", help="ISO datetime used as 'now' (for replays)")
    ap.add_argument("--skip-film-pages", action="store_true", help="do not fetch film pages (faster)")
    ap.add_argument("--venues", type=Path, help="data/venues.csv: also read the 18tickets and Webtic cinemas activated there")
    ap.add_argument("--no-platforms", action="store_true", help="read 18tickets only (skip Webtic and UCI)")
    ap.add_argument("--uci", action="store_true", help="also read UCI (off by default, see UCI_ENABLED)")
    a = ap.parse_args(argv)

    if a.venues:
        print(f"  cinemas added from {a.venues}: {add_venues_from_list(a.venues)}", file=sys.stderr)
    shows, errors = run_live() if a.mode == "live" else run_replay(a.raw)
    if a.mode == "live" and not a.no_platforms:
        more, errs = run_platforms(a.venues, a.out / "film_pages.json", uci=True if a.uci else None)
        shows += more
        errors.update(errs)
    if a.mode == "live" and not a.skip_film_pages:
        fetch_film_pages(shows, a.out / "film_pages.json")
    now = datetime.fromisoformat(a.now).astimezone(ROME) if a.now else None
    stats = write_outputs(shows, errors, a.out, now)
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
