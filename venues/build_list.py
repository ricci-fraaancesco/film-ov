#!/usr/bin/env python3
"""
Build the list of Italian cinemas: data/venues.csv

    python venues/build_list.py --out data/venues.csv

Sources, merged in this order (the first one that has a field wins):
1. our own configured cinemas (scraper/ov18tickets.py STOREFRONTS, site/build_data.py VENUE)
2. Cinema Revolution participants (rendicontazionecinemarevolution.it/cinema):
   name, address, city, postcode, province. About 1,100 cinemas and summer arenas.
3. Moviemedia advertising circuit (moviemedia.it/circuito): name, city, province, screens.
4. OpenStreetMap (amenity=cinema in Italy): coordinates, website, OSM id.
   OSM data is (c) OpenStreetMap contributors, ODbL. data/venues.csv is therefore
   published under the ODbL (see data/VENUES_LICENSE.md).

The list is a starting point. Each cinema is then checked on its own website by the
discovery step (website, ticketing platform, booking page), which updates status.
Existing manual work in data/venues.csv (status, website, platform, notes) is kept.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scraper"))
from regions import PROVINCE_REGION  # noqa: E402

USER_AGENT = "FilmOV-bot/0.1 (+https://github.com/ricci-fraaancesco/film-ov; building a list of cinemas)"
CR_URL = "https://rendicontazionecinemarevolution.it/cinema?page={}"
MM_URL = "https://www.moviemedia.it/circuito/"
OVERPASS = "https://overpass-api.de/api/interpreter"
OSM_QUERY = """[out:json][timeout:240];
area["ISO3166-1"="IT"][admin_level=2]->.it;
nwr["amenity"="cinema"](area.it);
out center tags;"""

FIELDS = ["id", "name", "city", "province", "region", "address", "postcode", "lat", "lon",
          "website", "screens", "kind", "platform", "booking_url", "status", "sources",
          "osm_id", "last_checked", "note"]
# fields a person (or the discovery step) may have edited: never overwritten by a rebuild
KEEP = ["website", "platform", "booking_url", "status", "last_checked", "note"]

GENERIC = set("""cinema cine cinemas cineteatro cinemateatro teatro sala sale multisala multisale
multiplex multicinema cityplex cineplex arena estiva supercinema cinematografo the il lo la le
di del della dei delle e d s spaziocinema""".split())


# ---------------------------------------------------------------- normalising
def ascii_lower(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


BRANDS = {"tsc": "the space cinema", "uci cinemas": "uci", "cinemas": "", "cinemax": "cinemax"}


def name_key(name: str, city: str = "", province: str = "") -> str:
    """'TSC Roma Moderno (RM)' and 'The Space Cinema - Moderno Roma' -> 'space moderno'."""
    n = ascii_lower(name.replace("★", ""))
    for k, v in BRANDS.items():
        n = re.sub(rf"\b{k}\b", v, n)
    drop = set(GENERIC) | set(ascii_lower(city).split()) | ({province.lower()} if province else set())
    words = [w for w in n.split() if w not in drop]
    return " ".join(words) or ascii_lower(name)


def city_key(city: str) -> str:
    c = ascii_lower(city)
    c = re.sub(r"\breggio di calabria\b", "reggio calabria", c)
    return re.sub(r"\s+", " ", c.replace("-", " ")).strip()


def street_key(addr: str) -> str:
    a = ascii_lower(addr)
    a = re.sub(r"\b(via|viale|v le|piazza|p zza|p za|piazzale|corso|c so|largo|l go|vicolo|strada|traversa|n|civico)\b", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def smart_title(s: str) -> str:
    """'CINEMA MODERNO' -> 'Cinema Moderno'; keeps names that already have mixed case."""
    s = re.sub(r"\s+", " ", (s or "").replace("★", "")).strip()
    if not s or (s != s.upper()):
        return s
    small = {"di", "del", "della", "dei", "delle", "e", "a", "al", "in", "da"}
    out = []
    for i, w in enumerate(s.lower().split(" ")):
        m = re.match(r"^(dell|dall|nell|sull|all|d|l)(['’])(.+)$", w)
        if m:  # "dell'imperatore" -> "dell'Imperatore", but "L'Aquila" at the start
            pre = m.group(1) if i else m.group(1).capitalize()
            out.append(pre + m.group(2) + m.group(3)[:1].upper() + m.group(3)[1:])
        else:
            out.append(w if i and w in small else w[:1].upper() + w[1:])
    return " ".join(out)


def slug(*parts: str) -> str:
    return re.sub(r"-+", "-", "-".join(ascii_lower(p).replace(" ", "-") for p in parts if p)).strip("-")


def same_name(a: str, b: str, city_a: str = "", city_b: str = "", prov_a: str = "", prov_b: str = "") -> bool:
    ka, kb = name_key(a, city_a, prov_a), name_key(b, city_b, prov_b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    ta, tb = set(ka.split()), set(kb.split())
    if min(len(ta), len(tb)) >= 1 and (ta <= tb or tb <= ta) and len(ta ^ tb) <= 2:
        return True  # "anteo palazzo" vs "anteo palazzo cinema milano"
    return SequenceMatcher(None, ka, kb).ratio() >= 0.88


# ---------------------------------------------------------------- sources
def http_get(url: str, **kw):
    import requests

    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"}, timeout=60, **kw)
    r.raise_for_status()
    return r


def parse_cr_page(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    out = []
    for tr in BeautifulSoup(html, "html.parser").select("table tr"):
        tds = [re.sub(r"\s+", " ", td.get_text(" ")).strip() for td in tr.find_all("td")]
        if len(tds) >= 5 and tds[0] and tds[2]:
            name, addr, city, cap, prov = tds[:5]
            out.append({"name": smart_title(name), "address": smart_title(addr), "city": smart_title(city),
                        "postcode": cap, "province": prov.upper()})
    return out


def fetch_cr(max_pages: int = 60) -> list[dict]:
    rows = []
    for p in range(1, max_pages + 1):
        got = parse_cr_page(http_get(CR_URL.format(p)).text)
        if not got:
            break
        rows += got
        time.sleep(1.5)
    print(f"  Cinema Revolution: {len(rows)} rows", file=sys.stderr)
    return rows


def parse_mm(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    out = []
    for tr in BeautifulSoup(html, "html.parser").select("table tr"):
        tds = [re.sub(r"\s+", " ", td.get_text(" ")).strip() for td in tr.find_all("td")]
        if len(tds) >= 5 and tds[0]:
            name, city, prov, region, screens = tds[:5]
            out.append({"name": smart_title(name), "city": smart_title(city) if city.upper() != "NONE" else "",
                        "province": prov.upper(), "region": region, "screens": screens if screens.isdigit() else "",
                        "note": "Moviemedia ★" if "★" in name else ""})
    return out


def fetch_mm() -> list[dict]:
    rows = parse_mm(http_get(MM_URL).text)
    print(f"  Moviemedia: {len(rows)} rows", file=sys.stderr)
    return rows


def parse_osm(data: dict) -> list[dict]:
    out = []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        if not t.get("name"):
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        street = " ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", "")] if x)
        out.append({
            "name": t["name"], "city": t.get("addr:city", ""), "postcode": t.get("addr:postcode", ""),
            "province": (t.get("addr:province", "") if len(t.get("addr:province", "")) == 2 else ""),
            "address": street, "lat": f"{lat:.6f}" if lat else "", "lon": f"{lon:.6f}" if lon else "",
            "website": t.get("website") or t.get("contact:website") or t.get("url") or "",
            "screens": t.get("screen", ""), "osm_id": f"{el['type']}/{el['id']}",
            "closed": any(k.startswith(("disused", "abandoned")) for k in t) or t.get("opening_hours") == "closed",
        })
    return out


def fetch_osm() -> list[dict]:
    import requests

    for attempt in range(3):  # Overpass is a shared free service: retry politely when busy
        r = requests.post(OVERPASS, data={"data": OSM_QUERY}, headers={"User-Agent": USER_AGENT}, timeout=300)
        if r.status_code in (429, 504) and attempt < 2:
            time.sleep(60 * (attempt + 1))
            continue
        r.raise_for_status()
        break
    rows = parse_osm(r.json())
    print(f"  OpenStreetMap: {len(rows)} cinemas with a name", file=sys.stderr)
    return rows


NOMINATIM = "https://nominatim.openstreetmap.org/reverse"


def fill_towns(osm: list[dict], cache_path: Path, fetch=None, delay: float = 1.1) -> int:
    """Find the town, postcode and province of OSM cinemas that miss them, from their coordinates.
    Uses OpenStreetMap's Nominatim, 1 request per second, each cinema only once ever
    (answers are kept in data/osm_towns.json)."""
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    if fetch is None:
        def fetch(lat, lon):
            r = http_get(NOMINATIM, params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1})
            return r.json().get("address", {})
    asked = 0
    for r in osm:
        if (r.get("city") and r.get("province")) or not r.get("lat"):
            continue
        key = r["osm_id"]
        if key not in cache:
            try:
                cache[key] = fetch(r["lat"], r["lon"])
            except Exception as e:
                print(f"  town for {key}: ERROR {e}", file=sys.stderr)
                continue
            asked += 1
            time.sleep(delay)
        a = cache[key]
        r["city"] = r.get("city") or a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
        r["postcode"] = r.get("postcode") or a.get("postcode", "")
        iso = a.get("ISO3166-2-lvl6", "")
        if iso.startswith("IT-") and len(iso) == 5:
            r["province"] = r.get("province") or iso[3:]
        if not r.get("address") and a.get("road"):
            r["address"] = " ".join(x for x in [a.get("road", ""), a.get("house_number", "")] if x)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    return asked


def our_cinemas() -> list[dict]:
    """The cinemas the scraper already reads, with their booking page."""
    import ov18tickets as mod  # scraper/ is on sys.path (see top of file)
    venue_info = {}
    bd = (HERE.parent / "site" / "build_data.py").read_text(encoding="utf-8")
    for m in re.finditer(r'\("([^"]+)","([^"]+)"\): \("([^"]*)", "([^"]*)", "([^"]*)"\)', bd):
        venue_info[(m.group(1), m.group(2))] = (m.group(3), m.group(5))
    out = []
    for storefront, cfg in mod.STOREFRONTS.items():
        for sub, (name, city) in cfg["venues"].items():
            addr, web = venue_info.get((city, name), ("", ""))
            out.append({"name": name, "city": city, "address": addr, "website": web, "platform": "18tickets",
                        "booking_url": f"https://{sub}.{storefront}/", "status": "active"})
    return out


# ---------------------------------------------------------------- merging
class VenueList:
    def __init__(self):
        self.rows: list[dict] = []
        self.by_city: dict[str, list[dict]] = {}

    def find(self, rec: dict) -> dict | None:
        ck = city_key(rec.get("city", ""))
        cands = self.by_city.get(ck, []) if ck else []
        if not cands and rec.get("postcode"):
            cands = [r for r in self.rows if r.get("postcode") == rec["postcode"]]
        if not cands and not ck:
            # no city and no usable postcode: accept a match only when the name is
            # distinctive and exactly one cinema in Italy has it
            nk = name_key(rec["name"])
            if len(nk) >= 6 and " " in nk:
                hits = [r for r in self.rows if name_key(r["name"], r.get("city", "")) == nk]
                return hits[0] if len(hits) == 1 else None
            return None
        # 1. same address in the same town: same cinema ('Sala 1' and 'Sala 2' in Via Verdi 24)
        sk = street_key(rec.get("address", ""))
        if sk and len(sk) > 4 and re.search(r"\d", sk):
            for r in cands:
                if street_key(r.get("address", "")) == sk:
                    return r
        # 2. same name once generic words, the town and the province are removed
        for r in cands:
            if same_name(r["name"], rec["name"], r.get("city", ""), rec.get("city", ""),
                         r.get("province", ""), rec.get("province", "")):
                return r
        return None

    def add(self, rec: dict, source: str) -> str:
        """Merge rec into the list. Returns 'new' or 'merged'."""
        hit = self.find(rec)
        if hit is None:
            row = {f: "" for f in FIELDS}
            row.update({k: v for k, v in rec.items() if k in FIELDS and v not in (None, "")})
            row["sources"] = source
            self.rows.append(row)
            self.by_city.setdefault(city_key(row["city"]), []).append(row)
            return "new"
        for k, v in rec.items():
            if k in FIELDS and v not in (None, "") and not hit.get(k):
                hit[k] = v
        if source not in hit["sources"].split("|"):
            hit["sources"] += "|" + source
        if rec.get("note") and rec["note"] not in hit.get("note", ""):
            hit["note"] = "; ".join(x for x in [hit.get("note", ""), rec["note"]] if x)
        if hit.get("city") == "" and rec.get("city"):
            self.by_city.setdefault(city_key(rec["city"]), []).append(hit)
        return "merged"


def finish(rows: list[dict]) -> None:
    used = set()
    for r in rows:
        r["region"] = r.get("region") or PROVINCE_REGION.get(r.get("province", ""), "")
        n = ascii_lower(r["name"])
        r["kind"] = "arena" if re.search(r"\barena\b|\bestiv", n) else "cinema"
        if not r.get("status"):
            r["status"] = "closed" if r.pop("_closed", False) else "to_check"
        r.pop("_closed", None)
        base = slug(r.get("city") or "senza-citta", r["name"])
        rid, i = base, 2
        while rid in used:
            rid, i = f"{base}-{i}", i + 1
        used.add(rid)
        r["id"] = r.get("id") or rid


def build(cr, mm, osm, ours, previous: dict[str, dict]) -> tuple[list[dict], dict]:
    vl = VenueList()
    stats = {}
    for name, recs, src in [("ours", ours, "filmov"), ("cr", cr, "cinemarevolution"), ("mm", mm, "moviemedia")]:
        res = [vl.add(r, src) for r in recs]
        stats[name] = {"rows": len(recs), "new": res.count("new"), "merged": res.count("merged")}
    res = []
    for r in osm:
        closed = r.pop("closed", False)
        out = vl.add(r, "osm")
        res.append(out)
        if closed and out == "new":
            vl.rows[-1]["_closed"] = True
    stats["osm"] = {"rows": len(osm), "new": res.count("new"), "merged": res.count("merged")}
    finish(vl.rows)
    # keep manual and discovery work from the previous file
    for r in vl.rows:
        old = previous.get(r["id"])
        if old:
            for k in KEEP:
                if old.get(k):
                    r[k] = old[k]
    vl.rows.sort(key=lambda r: (r["region"] or "~", r["city"].lower(), r["name"].lower()))
    return vl.rows, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/venues.csv"))
    ap.add_argument("--no-osm", action="store_true")
    a = ap.parse_args(argv)
    previous = {}
    if a.out.exists():
        with open(a.out, encoding="utf-8") as fh:
            previous = {r["id"]: r for r in csv.DictReader(fh)}
    errors = {}

    def safe(name, fn):
        import traceback
        try:
            return fn()
        except Exception as e:  # one source failing must not lose the others
            errors[name] = f"{type(e).__name__}: {e}"[:500]
            traceback.print_exc()
            return []

    cr = safe("cinemarevolution", fetch_cr)
    mm = safe("moviemedia", fetch_mm)
    osm = [] if a.no_osm else safe("osm", fetch_osm)
    if osm:
        asked = safe("osm_towns", lambda: [fill_towns(osm, a.out.parent / "osm_towns.json")])
        print(f"  towns looked up for OSM cinemas: {asked[0] if asked else 0}", file=sys.stderr)
    ours = safe("filmov", our_cinemas)
    if not cr and not osm:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        (a.out.parent / "venues_stats.json").write_text(json.dumps({"errors": errors}, indent=2), encoding="utf-8")
        print(json.dumps({"errors": errors}, indent=2))
        _summary(f"Lista cinema: nessuna fonte disponibile\n\n```\n{json.dumps(errors, indent=2)}\n```\n")
        return 1
    rows, stats = build(cr, mm, osm, ours, previous)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    summary = {"venues": len(rows), "sources": stats,
               "with_address": sum(1 for r in rows if r["address"]),
               "with_website": sum(1 for r in rows if r["website"]),
               "with_coordinates": sum(1 for r in rows if r["lat"]),
               "arenas": sum(1 for r in rows if r["kind"] == "arena"),
               "by_status": {s: sum(1 for r in rows if r["status"] == s) for s in sorted({r["status"] for r in rows})},
               "errors": errors}
    (a.out.parent / "venues_stats.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    _summary("Lista cinema\n\n```\n" + json.dumps(summary, indent=2, ensure_ascii=False) + "\n```\n")
    return 0


def _summary(text: str) -> None:
    import os
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    sys.exit(main())
