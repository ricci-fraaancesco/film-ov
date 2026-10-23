#!/usr/bin/env python3
"""
Find how each cinema sells tickets, from its own website, and update data/venues.csv.

    python venues/discover.py --venues data/venues.csv --batch 150

For each cinema with status 'to_check' (confirmed cinemas first):
- no website known          -> status no_website   (queue for the weekly research)
- website of a known chain  -> platform = chain     (The Space, UCI, ...: needs its own adapter)
- website is a social page  -> status social_only
- otherwise the homepage and up to 3 likely pages (programmazione, orari, biglietti...)
  are read, and links, iframes and scripts are searched for known ticketing platforms:
    18tickets  -> test read of the storefront; with OV-ready showtimes -> status active
                  (the nightly scraper then reads it)
    other known platform  -> status adapter_missing (we know the platform, no adapter yet)
    unknown booking site  -> status unknown_platform (its domain is in the note)
    nothing found         -> status no_booking_link
    site not reachable    -> status website_down

Polite: robots.txt is respected, 1 request per second, our user agent with a contact,
and at most --batch cinemas per run. Writes data/discovery_report.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scraper"))

USER_AGENT = "FilmOV-bot/0.1 (+https://github.com/ricci-fraaancesco/film-ov; checking how cinemas sell tickets)"
DELAY_S = 1.0
MAX_BYTES = 2_000_000

# booking platforms, matched on link / iframe / script hosts
PLATFORMS = {
    "18tickets": r"(^|\.)18tickets\.(it|net)$",
    "webtic": r"(^|\.)webtic\.it$",
    "liveticket": r"(^|\.)liveticket\.it$",
    "vivaticket": r"(^|\.)vivaticket\.(it|com)$",
    "ciaotickets": r"(^|\.)ciaotickets\.com$",
    "mytickets": r"(^|\.)mytickets\.it$",
    "boxol": r"(^|\.)boxol\.it$",
    "ticketone": r"(^|\.)ticketone\.it$",
    "eventbrite": r"(^|\.)eventbrite\.(it|com)$",
    "cinebot": r"(^|\.)cinebot\.it$",
    "vista": r"(^|\.)(vista\.co|vistaentertainment\.com)$",
}
# chains with their own booking system: recognised from the cinema's website itself
CHAINS = {
    "thespace": r"(^|\.)thespacecinema\.it$",
    "uci": r"(^|\.)ucicinemas\.it$",
    "giometti": r"(^|\.)giomettirealestatecinema\.it$",
    "cinelandia": r"(^|\.)cinelandia\.it$",
    "notorious": r"(^|\.)notoriouscinemas\.it$",
    "eplanet": r"(^|\.)eplanetcinemas\.it$",
    "ferrero": r"(^|\.)ferrerocinemas\.it$",
    "movieplanet": r"(^|\.)movieplanetgroup\.it$",
    "anteo": r"(^|\.)spaziocinema\.info$|(^|\.)anteospaziocinema\.com$",
}
SOCIAL = r"(^|\.)(facebook\.com|instagram\.com|fb\.me|linktr\.ee|tiktok\.com)$"
NOT_BOOKING = r"(^|\.)(google\.[a-z.]+|goo\.gl|youtube\.com|youtu\.be|twitter\.com|x\.com|whatsapp\.com|wa\.me|" \
              r"apple\.com|tripadvisor\.[a-z.]+|wikipedia\.org|w3\.org|iubenda\.com|cookiebot\.com|" \
              r"googletagmanager\.com|gstatic\.com|cloudflare\.com|jquery\.com|wordpress\.org|wp\.com|" \
              r"mymovies\.it|comingsoon\.it|imdb\.com|themoviedb\.org|trovacinema\.it|cinemap\.it|" \
              r"paypal\.com|stripe\.com|mailchimp\.com|spotify\.com|vimeo\.com|bit\.ly|" \
              r"facebook\.com|instagram\.com|fb\.me|linktr\.ee|tiktok\.com|pinterest\.[a-z.]+|linkedin\.com)$"
BOOKING_WORDS = r"acquist|bigliett|prenot|ticket|compra|booking|buy|cassa|online"
PAGE_WORDS = [r"programm", r"orari", r"bigliett|acquist|prenot", r"in.?sala|film|cartellon|calendar"]
CONFIRMED = ("filmov", "cinemarevolution", "moviemedia")
CHAINS_READ: set[str] = set()  # chains read as a whole by an adapter (UCI is off: it blocks automated requests)


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def match(table: dict, host: str) -> str | None:
    return next((k for k, rx in table.items() if re.search(rx, host)), None)


def normalise_website(w: str) -> str:
    w = (w or "").strip().split()[0] if (w or "").strip() else ""
    if w and not re.match(r"^https?://", w, re.I):
        w = "http://" + w
    return w


# ---------------------------------------------------------------- page analysis (pure, tested)
def analyse(html: str, base_url: str) -> dict:
    """Links found on one page: booking platforms, other booking-looking domains, candidate pages."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    site = host_of(base_url).removeprefix("www.")
    found: dict[str, str] = {}
    unknown: Counter = Counter()
    pages: list[tuple[int, str]] = []
    urls = []
    for tag, attr in (("a", "href"), ("iframe", "src"), ("script", "src"), ("form", "action"), ("link", "href")):
        for el in soup.find_all(tag):
            v = el.get(attr)
            if v:
                urls.append((tag, urljoin(base_url, v.strip()), el.get_text(" ", strip=True)[:80] if tag == "a" else ""))
    # platform URLs written inside scripts or data attributes
    for m in re.finditer(r"https?://[a-z0-9.-]+\.(?:18tickets\.it|webtic\.it|liveticket\.it|vivaticket\.(?:it|com))[^\s\"'<>)]*", html, re.I):
        urls.append(("text", m.group(0), ""))
    for tag, url, text in urls:
        h = host_of(url)
        if not h:
            continue
        p = match(PLATFORMS, h)
        if p:
            # prefer a link to a show or a storefront page over a bare script URL
            if p not in found or (tag == "a" and found[p].endswith(".js")):
                found[p] = url
            continue
        c = match(CHAINS, h)
        if c and h.removeprefix("www.") != site:
            found.setdefault(c, url)
            continue
        if h.removeprefix("www.") == site or h.endswith("." + site):
            if tag == "a":
                low = (url + " " + text).lower()
                score = sum(3 - i // 2 for i, rx in enumerate(PAGE_WORDS) if re.search(rx, low))
                if score and not re.search(r"\.(pdf|jpe?g|png|zip)(\?|$)|privacy|cookie|contatt|news/|#", low):
                    pages.append((score, url.split("#")[0]))
            continue
        if tag == "a" and not re.search(NOT_BOOKING, h) and re.search(BOOKING_WORDS, (url + " " + text).lower()):
            unknown[h] += 1
    from webtic import WHITE_LABEL_URL, local_ids_in_text
    webtic_ids = local_ids_in_text(html) if re.search(r"webtic|seatsframe\.php|film-ricercato", html, re.I) else []
    if "webtic" not in found:  # a white-label Webtic site: its booking links stay on its own domain
        m = re.search(WHITE_LABEL_URL, html.replace("&amp;", "&"), re.I)
        if m:
            found["webtic"] = urljoin(base_url, m.group(0))
    best_pages = []
    for _, u in sorted(pages, key=lambda x: -x[0]):
        if u not in best_pages and u.rstrip("/") != base_url.rstrip("/"):
            best_pages.append(u)
    return {"platforms": found, "unknown": dict(unknown), "pages": best_pages[:3], "webtic_ids": webtic_ids}


def storefront_of(url: str) -> tuple[str, str, str]:
    """'https://odeon.ccb.18tickets.it/film/1/x' -> ('ccb.18tickets.it', 'odeon', 'https://odeon.ccb.18tickets.it/')."""
    h = host_of(url)
    parts = h.split(".")
    if len(parts) >= 4:   # venue.group.18tickets.it
        return ".".join(parts[-3:]), ".".join(parts[:-3]), f"https://{h}/"
    return h, "", f"https://{h}/"


# ---------------------------------------------------------------- network
class Fetcher:
    def __init__(self, delay: float = DELAY_S):
        import requests

        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"})
        self.delay = delay
        self.robots: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self.robots:
            rp = RobotFileParser()
            try:
                r = self.s.get(key + "/robots.txt", timeout=10)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:
                rp.parse([])
            self.robots[key] = rp
        rp = self.robots[key]
        return rp.can_fetch(USER_AGENT, url) if rp else True

    def get(self, url: str) -> tuple[str, str]:
        """Returns (final_url, html). Raises on errors."""
        if not self.allowed(url):
            raise PermissionError("robots.txt")
        r = self.s.get(url, timeout=20, allow_redirects=True, stream=True)
        r.raise_for_status()
        body = r.raw.read(MAX_BYTES, decode_content=True)
        time.sleep(self.delay)
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype:
            raise ValueError(f"not a web page ({ctype or 'unknown type'})")
        return r.url, body.decode(r.encoding or "utf-8", errors="replace")


def test_18tickets(fetch: Fetcher, page_url: str) -> tuple[int, int, set[str]]:
    """Read a storefront page with the real parser. Returns (films, showtimes, cinema subdomains)."""
    from ov18tickets import parse_storefront_html

    storefront, sub, root = storefront_of(page_url)
    _, html = fetch.get(root)
    shows = parse_storefront_html(html, storefront, root)
    return len({s.film_id for s in shows}), len(shows), {s.venue_sub for s in shows}


def check_webtic(fetch: "Fetcher", url: str, ids: list[str]) -> dict:
    """Test read of a Webtic cinema: with a programme it becomes active."""
    import webtic

    lid = webtic.local_id_from_url(url) or (ids[0] if len(set(ids)) == 1 else None)
    if not lid:
        why = f"più numeri Webtic sulla pagina: {', '.join(sorted(set(ids)))[:60]}" if ids else "numero del cinema Webtic non trovato"
        return {"status": "needs_review", "platform": "webtic", "booking_url": url, "note": why}

    def get_json(u, params=None):
        import requests
        r = fetch.s.get(u, params=params, timeout=30)
        r.raise_for_status()
        time.sleep(fetch.delay)
        return r.json()
    try:
        shows, _, local = webtic.read_cinema(get_json, lid)
    except Exception as e:
        return {"status": "needs_review", "platform": "webtic", "booking_url": url, "note": f"Webtic non letto: {type(e).__name__}"[:120]}
    district = (local.get("DistrictAbbreviation") or "XX").upper()
    page = f"https://www.webtic.it/app/shopping/loadLocal/{district}/{lid}"
    if not shows:
        return {"status": "needs_review", "platform": "webtic", "booking_url": page, "note": "Webtic senza spettacoli in programma"}
    films = len({s.film_id for s in shows})
    return {"status": "active", "platform": "webtic", "booking_url": page,
            "note": f"Webtic letto: {films} film, {len(shows)} spettacoli ({(local.get('Description') or '').title()}, {local.get('Town', '')})"}


# ---------------------------------------------------------------- one cinema
def check(row: dict, fetch: Fetcher) -> dict:
    """Returns the fields to update for this cinema."""
    site = normalise_website(row.get("website", ""))
    if not site:
        return {"status": "no_website"}
    h = host_of(site)
    if re.search(SOCIAL, h):
        return {"status": "social_only", "note": "solo pagina social"}
    # a Webtic cinema whose number is already known (e.g. set in review): test-read it directly
    if row.get("platform") == "webtic" and row.get("booking_url"):
        from webtic import local_id_from_url
        if local_id_from_url(row["booking_url"]):
            return check_webtic(fetch, row["booking_url"], [])
    chain = match(CHAINS, h)
    if chain:
        # UCI is read as a whole chain by scraper/uci.py, so its cinemas count as active
        return {"status": "active" if chain in CHAINS_READ else "adapter_missing", "platform": chain, "booking_url": site}
    wt_ids: list[str] = []
    if match(PLATFORMS, h):  # the 'website' is already a booking page
        found, unknown, pages, final = {match(PLATFORMS, h): site}, {}, [], site
    else:
        try:
            final, html = fetch.get(site)
        except PermissionError:
            return {"status": "needs_review", "note": "robots.txt non permette la lettura"}
        except Exception as e:
            return {"status": "website_down", "note": f"sito non raggiungibile: {type(e).__name__}"[:120]}
        a = analyse(html, final)
        found, unknown, pages = a["platforms"], Counter(a["unknown"]), a["pages"]
        wt_ids = list(a.get("webtic_ids", []))
        for p in pages:
            if found:
                break
            try:
                purl, phtml = fetch.get(p)
            except Exception:
                continue
            b = analyse(phtml, purl)
            found.update({k: v for k, v in b["platforms"].items() if k not in found})
            unknown.update(b["unknown"])
            wt_ids += [i for i in b.get("webtic_ids", []) if i not in wt_ids]
    upd = {"website": final if final != site and host_of(final) else ""}
    if "18tickets" in found:
        url = found["18tickets"]
        storefront, sub, root = storefront_of(url)
        try:
            films, shows, subs = test_18tickets(fetch, url)
        except Exception as e:
            return {**upd, "status": "needs_review", "platform": "18tickets", "booking_url": root,
                    "note": f"18tickets non letto: {type(e).__name__}"[:120]}
        if shows and not sub:
            if len(subs) != 1:  # a group storefront: we must know which of its cinemas this is
                return {**upd, "status": "needs_review", "platform": "18tickets", "booking_url": root,
                        "note": f"18tickets di gruppo ({', '.join(sorted(subs))[:80]}): scegliere il cinema"}
            only = next(iter(subs))
            if only != "main":  # "main" = the storefront's own address, keep it as it is
                root = f"https://{only}.{storefront}/"
        if shows:
            return {**upd, "status": "active", "platform": "18tickets", "booking_url": root,
                    "note": f"18tickets letto: {films} film, {shows} spettacoli"}
        return {**upd, "status": "needs_review", "platform": "18tickets", "booking_url": root,
                "note": "18tickets senza spettacoli o con più cinema: scegliere la pagina giusta"}
    if "webtic" in found:
        return {**upd, **check_webtic(fetch, found["webtic"], wt_ids)}
    if found:
        p, url = next(iter(found.items()))
        return {**upd, "status": "adapter_missing", "platform": p, "booking_url": url}
    if unknown:
        dom, _ = unknown.most_common(1)[0]
        return {**upd, "status": "unknown_platform", "platform": "", "note": f"biglietti su {dom}"}
    return {**upd, "status": "no_booking_link", "note": "nessun link per i biglietti trovato"}


# ---------------------------------------------------------------- main
FIELDS_UPDATED = ("status", "platform", "booking_url", "website", "note")


def priority(r: dict) -> tuple:
    confirmed = any(s in r.get("sources", "") for s in CONFIRMED)
    return (0 if confirmed else 1, 0 if r.get("website") else 1, r.get("region", "~"), r.get("city", ""))


def run(rows: list[dict], fetch: Fetcher, batch: int, now: str) -> Counter:
    todo = sorted((r for r in rows if r.get("status") == "to_check" and r.get("website")), key=priority)[:batch]
    # cinemas without a website need no request: queue them for research right away
    for r in rows:
        if r.get("status") == "to_check" and not r.get("website"):
            r["status"], r["last_checked"] = "no_website", now
    counts = Counter()
    used = {r["booking_url"]: r for r in rows if r.get("status") == "active" and r.get("booking_url")}
    for i, r in enumerate(todo, 1):
        try:
            upd = check(r, fetch)
        except Exception as e:  # never stop the batch for one cinema
            upd = {"status": "needs_review", "note": f"errore: {type(e).__name__}"[:120]}
        if upd.get("status") == "active":
            other = used.get(upd.get("booking_url"))
            if other is not None and other is not r:  # never put two cinemas on one storefront page
                upd = {**upd, "status": "needs_review",
                       "note": f"stessa pagina 18tickets di {other['name']} ({other['city']}): verificare"}
            else:
                used[upd["booking_url"]] = r
        for k in FIELDS_UPDATED:
            if upd.get(k):
                r[k] = upd[k]
        r["last_checked"] = now
        counts[r["status"]] += 1
        print(f"  [{i}/{len(todo)}] {r['city']} / {r['name']}: {r['status']} {r.get('platform', '')}", file=sys.stderr)
    return counts


def write_report(rows: list[dict], counts: Counter, path: Path, now: str) -> str:
    total = Counter(r["status"] for r in rows)
    plats = Counter(r["platform"] for r in rows if r.get("platform"))
    unknown = Counter(re.sub(r"^biglietti su ", "", r["note"]) for r in rows if r["status"] == "unknown_platform")
    lines = [f"# Controllo dei siti dei cinema ({now[:10]})", "",
             "## Questa notte", ""] + [f"- {k}: {v}" for k, v in counts.most_common()] + [
             "", "## Totale per stato", ""] + [f"- {k}: {v}" for k, v in total.most_common()] + [
             "", "## Piattaforme trovate", ""] + [f"- {k}: {v}" for k, v in plats.most_common()] + [
             "", "## Siti di biglietteria sconosciuti (candidati per un nuovo adapter)", ""] + (
             [f"- {k}: {v}" for k, v in unknown.most_common(20)] or ["- nessuno"])
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


TRACKED = ("status", "platform", "booking_url", "website", "note", "last_checked")


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def diff_rows(before: list[dict], after: list[dict]) -> dict[str, dict]:
    """Only what this run changed, per cinema id: {id: {field: new value}}."""
    old = {r["id"]: r for r in before}
    out = {}
    for r in after:
        o = old.get(r["id"], {})
        ch = {k: r.get(k, "") for k in TRACKED if r.get(k, "") != o.get(k, "")}
        if ch:
            out[r["id"]] = ch
    return out


def apply_updates(rows: list[dict], updates: dict[str, dict]) -> int:
    """Apply a run's changes to a (possibly newer) list. Rows that a person set to
    something other than to_check / no_website in the meantime are left alone."""
    n = 0
    for r in rows:
        u = updates.get(r["id"])
        if u and r.get("status") in ("to_check", "no_website", ""):
            r.update(u)
            n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venues", type=Path, default=Path("data/venues.csv"))
    ap.add_argument("--batch", type=int, default=150)
    ap.add_argument("--updates-out", type=Path, help="also write this run's changes as JSON")
    ap.add_argument("--apply", type=Path, help="only apply a JSON of changes to --venues, then exit")
    a = ap.parse_args(argv)
    fields, rows = read_csv(a.venues)
    if a.apply:
        n = apply_updates(rows, json.loads(a.apply.read_text(encoding="utf-8")))
        write_csv(a.venues, fields, rows)
        print(f"applied changes to {n} cinemas")
        return 0
    before = [dict(r) for r in rows]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts = run(rows, Fetcher(), a.batch, now)
    write_csv(a.venues, fields, rows)
    if a.updates_out:
        a.updates_out.write_text(json.dumps(diff_rows(before, rows), ensure_ascii=False, indent=0), encoding="utf-8")
    report = write_report(rows, counts, a.venues.parent / "discovery_report.md", now)
    print(report)
    import os
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
