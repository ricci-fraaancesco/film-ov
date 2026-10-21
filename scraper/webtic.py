"""
Webtic adapter (Crea Informatica): reads a cinema's whole programme from the JSON
service behind the Webtic booking pages.

    https://secure.webtic.it/api/wtjsonservices.ashx?localid=<id>&trackid=33&wtid=getFullScheduling
    https://secure.webtic.it/api/wtjsonservices.ashx?localid=<id>&trackid=33&wtid=getLocalInfo&languageid=it

Each event (film) has Title, OriginalTitle, Director, Year, Description, Picture and
EventProperties such as {"EventProperty": "O.V."}, {"EventProperty": "EN",
"EventPropertyCategory": "LANGUAGE"} or {"EventProperty": "SUB-IT", ...}. The category
is often "CATEGORIA NON DEFINITA", so the values are read whatever the category.
Each performance has PerformanceId, StartTime (local time) and Screen / ScreenName.

Booking link: the film's page at that cinema on webtic.it, which lists all its times
(a link to one performance goes through a Webtic login first):
    https://www.webtic.it/app/shopping/loadEvent/<district>/<localId>/<performanceId>/<eventId>
"""
from __future__ import annotations

import base64
import re
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

from langs import OV_WORDS, clean_html, language_text, lang_name

API = "https://secure.webtic.it/api/wtjsonservices.ashx"
PICTURE_BASE = "https://secure.webtic.it/angwt/"

ID_PATTERNS = [
    r"[?&#]localid=(\d{3,6})", r"localId=(\d{3,6})", r"/loadLocal/[A-Za-z]{2}/(\d{3,6})",
    r"/loadEvent/[A-Za-z]{2}/(\d{3,6})/", r"[?&]idcinema=(\d{3,6})", r"[?&]lid=(\d{3,6})",
    r"#/local/\w+/\d+/(\d{3,6})", r"#/event/\w+/\d+/(\d{3,6})/",
]


def local_id_from_url(url: str) -> str | None:
    """Find the Webtic cinema number in any of the link styles cinemas use."""
    u = unquote((url or "").replace("\\u0026", "&").replace("&amp;", "&"))
    for rx in ID_PATTERNS:
        m = re.search(rx, u, re.I)
        if m:
            return m.group(1)
    q = parse_qs(urlparse(u).query)
    for pu in q.get("pu", []):  # base64 of the webtic.it page that embeds the booking app
        try:
            inner = base64.b64decode(pu + "=" * (-len(pu) % 4)).decode("utf-8", "ignore")
            found = local_id_from_url(inner)
            if found:
                return found
        except Exception:
            pass
    return None


def local_ids_in_text(text: str) -> list[str]:
    ids = []
    for rx in ID_PATTERNS:
        for m in re.finditer(rx, (text or "").replace("\\u0026", "&").replace("&amp;", "&"), re.I):
            if m.group(1) not in ids:
                ids.append(m.group(1))
    return ids


def event_values(event: dict) -> list[str]:
    vals = [str(p).strip().upper() for p in event.get("Properties") or []]
    for p in event.get("EventProperties") or []:
        vals.append(str(p.get("EventProperty", "")).strip().upper())
    return [v for v in vals if v]


def ov_info(event: dict) -> tuple[bool, str, str, str]:
    """(is_ov, reason, original language code, subtitles code)."""
    vals = event_values(event)
    title = (event.get("Title") or "").upper()
    subs = next((v[4:] for v in vals if v.startswith("SUB-")), "")
    langs = [v for v in vals if lang_name(v)]
    lang = next((v for v in langs if lang_name(v) != "Italiano"), "")
    if re.search(r"\((IT|ITA)\)|\bDOPPIATO\b|\bIN ITALIANO\b", title):
        return False, "dubbed", "", ""
    if any(v in OV_WORDS for v in vals):
        return True, "webtic O.V.", lang, subs
    if lang:
        return True, "webtic language", lang, subs
    if subs and not any(lang_name(v) == "Italiano" for v in langs):
        return True, "webtic subtitles", "", subs
    if re.search(r"\b(V\.?\s?O\.?S?\.?|ORIGINAL (VERSION|LANGUAGE)|LINGUA ORIGINALE|VERSIONE ORIGINALE)\b", title):
        return True, "title", "", ""
    return False, "no OV signal", "", ""


def parse_scheduling(data: dict, local_id: str, district: str, cinema: str, city: str) -> tuple[list, dict]:
    """Returns (shows, film pages) for one cinema. Film pages carry the synopsis, year,
    director and poster for build_data, keyed by the show's film_url."""
    from ov18tickets import ROME, Show, clean_title

    sched = ((data or {}).get("DS") or {}).get("Scheduling") or {}
    shows, pages = [], {}
    for ev in sched.get("Events") or []:
        ov, reason, lang, subs = ov_info(ev)
        event_id = str(ev.get("EventId"))
        title = (ev.get("Title") or "").strip()
        film_url = f"https://www.webtic.it/app/shopping/loadEvent/{district}/{local_id}/0/{event_id}"
        poster = PICTURE_BASE + ev["Picture"] if ev.get("Picture") else ""
        language = language_text(lang, subs, ov) if ov else "Italiano"
        label = ", ".join(v for v in event_values(ev) if v not in OV_WORDS and not lang_name(v)
                          and not v.startswith("SUB-") and v not in ("2D",))
        if ov:
            year = (ev.get("Year") or "").strip()
            pages[film_url] = {
                "synopsis": clean_html(ev.get("Description") or ""),
                "year": int(year) if year.isdigit() else None,
                "director": (ev.get("Director") or "").strip(),
                "genre": (ev.get("Category") or "").strip(),
                "poster": poster,
                "original_title": (ev.get("OriginalTitle") or "").strip(),
            }
        for day in ev.get("Days") or []:
            for p in day.get("Performances") or []:
                try:
                    dt = datetime.fromisoformat(p["StartTime"]).replace(tzinfo=ROME)
                except (KeyError, ValueError):
                    continue
                pid = str(p.get("PerformanceId"))
                shows.append(Show(
                    storefront="webtic.it", venue_sub=str(local_id), cinema=cinema, city=city,
                    film_id=f"wt{local_id}-{event_id}", title_raw=title, title=clean_title(title),
                    language=language, label=label[:60], starts_at=dt.isoformat(),
                    date=dt.strftime("%Y-%m-%d"), time=dt.strftime("%H:%M"),
                    screen=(p.get("ScreenName") or p.get("Screen") or "").strip().title(),
                    booking_url=f"https://www.webtic.it/app/shopping/loadEvent/{district}/{local_id}/{pid}/{event_id}",
                    is_ov=ov, ov_reason=reason,
                    subtitles={"Italiano": "sub IT", "Inglese": "sub EN"}.get(lang_name(subs), ""),
                    film_url=film_url, poster=poster, director=(ev.get("Director") or "").strip(),
                ))
    return shows, pages


def read_cinema(get_json, local_id: str, cinema: str = "", city: str = "") -> tuple[list, dict, dict]:
    """Fetch and parse one cinema. get_json(url, params) -> dict. Returns (shows, pages, info)."""
    info = get_json(API, {"languageid": "it", "localid": local_id, "trackid": 33, "wtid": "getLocalInfo"})
    local = ((info or {}).get("DS") or {}).get("Local") or {}
    district = (local.get("DistrictAbbreviation") or local.get("District") or "XX").upper()
    sched = get_json(API, {"localid": local_id, "trackid": 33, "wtid": "getFullScheduling"})
    shows, pages = parse_scheduling(sched, local_id, district, cinema or (local.get("Description") or "").title(),
                                    city or (local.get("Town") or ""))
    return shows, pages, local
