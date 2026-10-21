"""
UCI Cinemas adapter: reads the programme of every UCI cinema in Italy from the JSON
back end of ucicinemas.it (robots.txt allows everything).

    https://backend.ucicinemas.it/api/theatres                      all cinemas (name, slug, city, address)
    https://backend.ucicinemas.it/api/theatres/<slug>/programming   whole programme, one call per cinema
    https://backend.ucicinemas.it/api/movies/<slug>                 film details (directors), only for OV films

The programme is a list of {"<date>": [movie, ...]}. A movie has screens:
[{"<screen type>": [variant, ...]}]; a variant has language {"name": "ENG"}, subtitles
{"name": "ITA"} or null, and performances with starts_at (local time) and cart_link,
the purchase page of that exact screening.
"""
from __future__ import annotations

import re
from datetime import datetime

from langs import clean_html, language_text, lang_name

API = "https://backend.ucicinemas.it/api"
SITE = "https://ucicinemas.it"


def theatres(get_json) -> list[dict]:
    out = []
    for t in (get_json(f"{API}/theatres", None) or {}).get("data") or []:
        if not t.get("slug"):
            continue
        addr = clean_html(t.get("address") or "").split("\n")[0]
        out.append({"slug": t["slug"], "name": (t.get("name") or "").strip(), "city": (t.get("city") or "").strip(),
                    "address": addr, "lat": t.get("latitude") or "", "lon": t.get("longitude") or ""})
    return out


def _sub_name(v) -> str:
    if isinstance(v, dict):
        return v.get("name") or v.get("slug") or ""
    return v or ""


def parse_programming(data: dict, theatre: dict) -> tuple[list, dict]:
    """Returns (shows, film pages). Only fields from the programme; directors are added later."""
    from ov18tickets import ROME, Show, clean_title

    shows, pages, seen = [], {}, set()
    for block in (data or {}).get("data") or []:
        items = block.items() if isinstance(block, dict) else []
        for _date, movies in items:
            for m in movies or []:
                title = (m.get("title") or "").strip()
                film_url = f"{SITE}/movies/{m.get('slug')}"
                for screen_group in m.get("screens") or []:
                    for screen_type, variants in (screen_group or {}).items():
                        for v in variants or []:
                            lang = (v.get("language") or {}).get("name") or (v.get("language") or {}).get("slug") or ""
                            subs = _sub_name(v.get("subtitles"))
                            ov = bool(lang) and lang_name(lang) != "Italiano"
                            language = language_text(lang, subs, ov) if ov else "Italiano"
                            if ov and film_url not in pages:
                                year = str(v.get("release_date") or "")[:4]
                                pages[film_url] = {
                                    "synopsis": re.sub(r"\n?Si ricorda che il film inizia.*$", "", clean_html(m.get("description") or ""), flags=re.S | re.I).strip(),
                                    "year": int(year) if year.isdigit() else None,
                                    "director": "",
                                    "genre": ", ".join(g.get("name", "") for g in m.get("genres") or [] if g.get("name")),
                                    "poster": m.get("poster") or m.get("top_image") or "",
                                    "uci_slug": m.get("slug"),
                                }
                            for p in v.get("performances") or []:
                                key = (p.get("id") or p.get("external_id"), theatre["slug"])
                                if key in seen:
                                    continue
                                seen.add(key)
                                try:
                                    dt = datetime.fromisoformat(p["starts_at"]).replace(tzinfo=ROME)
                                except (KeyError, ValueError):
                                    continue
                                link = p.get("cart_link") or ""
                                room = (p.get("room") or "").strip().title()
                                shows.append(Show(
                                    storefront="ucicinemas.it", venue_sub=theatre["slug"],
                                    cinema=theatre["name"], city=theatre["city"],
                                    film_id=f"uci-{m.get('id')}", title_raw=title, title=clean_title(title),
                                    language=language,
                                    label=screen_type if screen_type not in ("2D", "Movies") else "",
                                    starts_at=dt.isoformat(), date=dt.strftime("%Y-%m-%d"), time=dt.strftime("%H:%M"),
                                    screen=room + (f" {screen_type}" if screen_type not in ("2D",) and screen_type.upper() not in room.upper() else ""),
                                    booking_url=SITE + link if link.startswith("/") else (link or film_url),
                                    is_ov=ov, ov_reason="uci language" if ov else "italian",
                                    subtitles={"Italiano": "sub IT", "Inglese": "sub EN"}.get(lang_name(subs), ""),
                                    film_url=film_url, poster=m.get("poster") or "", director="",
                                ))
    return shows, pages


def add_directors(get_json, pages: dict, cache: dict) -> int:
    """Fill the director of OV films from /api/movies/<slug>, once per film (cache = film_pages)."""
    asked = 0
    for url, page in pages.items():
        cached = cache.get(url) or {}
        if cached.get("director"):
            page["director"] = cached["director"]
            continue
        slug = page.get("uci_slug")
        if not slug:
            continue
        try:
            d = (get_json(f"{API}/movies/{slug}", None) or {}).get("data") or {}
            page["director"] = ", ".join(x.get("name", "") for x in d.get("directors") or [] if x.get("name"))
            asked += 1
        except Exception:
            pass
    return asked
