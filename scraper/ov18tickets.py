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
    # TODO: Barberini (multisala.barberini.18tickets.it returns 404 at root),
    # Troisi, Greenwich: storefront URLs still to confirm.
}

# --------------------------------------------------------------------------
# OV detection. Order matters: an explicit "dubbed" wins over everything.
# --------------------------------------------------------------------------
RE_DUBBED = re.compile(r"doppiag|doppiat", re.I)
RE_SILENT = re.compile(r"^\s*muto\s*$", re.I)
RE_OV_TITLE = re.compile(
    r"(^|[\s\-\(])v\.\s?o\.?(\s?s\.?)?($|[\s\)])"
    r"|original (language|version)|lingua originale|versione originale|\bvos\b",
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


def subtitle_info(language: str) -> str:
    l = language.lower()
    m = re.search(r"sottotitol\w*(.*)$", l)
    if not m:
        return ""
    after = m.group(1)
    it, en = "italian" in after, "ingles" in after
    if it and en:
        return "sub IT+EN"
    if en:
        return "sub EN"
    return "sub IT"


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


def venue_for(storefront: str, sub: str) -> tuple[str, str]:
    venues = STOREFRONTS.get(storefront, {}).get("venues", {})
    return venues.get(sub, (sub.title(), "?"))


def make_show(storefront, sub, film_id, title, language, label, epoch_s, screen, uuid) -> Show:
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
        subtitles=subtitle_info(language),
    )


# --------------------------------------------------------------------------
# HTML parsing (live mode)
# --------------------------------------------------------------------------
def parse_storefront_html(html: str, storefront: str) -> list[Show]:
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse

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
                shows[key] = make_show(storefront, sub, film_id, title, language, label, epoch_s, screen, uuid)
    return list(shows.values())


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
                got = parse_storefront_html(html, storefront)
                all_shows.extend(got)
                print(f"  {page}: {len(got)} shows", file=sys.stderr)
            except Exception as e:  # keep going, monitoring will flag it
                errors[page] = repr(e)
                print(f"  {page}: ERROR {e}", file=sys.stderr)
            time.sleep(REQUEST_DELAY_S)
    return all_shows, errors


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
              "starts_at", "ov_reason"]


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
    a = ap.parse_args(argv)

    shows, errors = run_live() if a.mode == "live" else run_replay(a.raw)
    now = datetime.fromisoformat(a.now).astimezone(ROME) if a.now else None
    stats = write_outputs(shows, errors, a.out, now)
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
