"""
Static pages for the site, following claude/url-structure.md and claude/design-decisions.md.

    /it/                              home: near me, cities, films this week
    /it/<city>/                       city: 7-day strip, by film or by cinema
    /it/<city>/<cinema>/              cinema
    /it/film/                         all films on now
    /it/film/<film>/                  film: every city where it's on
    /it/film/<film>/<city>/           film x city: every screening, by day
    /it/cinema/                       all cinemas, grouped by city
    /it/data.json                     small data file for search and "near me"

Every page works without JavaScript (all days are in the HTML). site.js only hides
screenings that have started, switches days and views, and adds search and distances.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
HERE = Path(__file__).parent
BRAND = "linguaoriginale"
CONTACT = "ciao@linguaoriginale.com"

WD = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
WD_SHORT = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]
GENERIC = re.compile(r"^(pop up cinema|cinema teatro|cineteatro|multicinema|multisala|multiplex|cinema|sala)\s+", re.I)


def e(s) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def km(a, b) -> float | None:
    if None in (a[0], a[1], b[0], b[1]):
        return None
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def long_date(d: date) -> str:
    return f"{WD[d.weekday()].capitalize()} {d.day} {MONTHS[d.month - 1]}"


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def al(name: str) -> str:
    """Italian preposition before a cinema name: al Nuovo Olimpia, all'Arlecchino, alla Sala Cervi."""
    low = name.lower()
    if low.startswith(("sala ", "multisala ")):
        return "alla " + name
    if low[:1] in "aeiouàèéìòù":
        return "all'" + name
    return "al " + name


# ---------------------------------------------------------------- languages and badges

SUB_SHORT = {"sott. ITA": "IT", "sott. ENG": "EN", "sott. ITA + ENG": "IT+EN"}


def lang_badge(f) -> str:
    l = (f.get("l") or "").strip()
    if not l or l.lower() == "lingua originale":
        return "Lingua originale"
    parts = [p.strip() for p in re.split(r",|\s+e\s+", l) if p.strip()]
    if len(parts) > 2:
        return "Più lingue"
    if len(parts) == 2:
        return parts[0][:1].upper() + parts[0][1:] + " e " + parts[1].lower()
    return l[:1].upper() + l[1:]


def sub_short(f) -> str:
    return SUB_SHORT.get(f.get("s") or "", "")


def lang_text(f) -> str:
    """'Olandese, sott. IT' for one-line use."""
    s = sub_short(f)
    return lang_badge(f) + (f", sott. {s}" if s else "")


def badges(f, label: str = "") -> str:
    out = [f'<span class="b b-lang">{e(lang_badge(f))}</span>']
    if sub_short(f):
        out.append(f'<span class="b b-sub">Sott. {e(sub_short(f))}</span>')
    if label:
        out.append(f'<span class="b b-lab">{e(label)}</span>')
    return '<span class="badges">' + "".join(out) + "</span>"


# ---------------------------------------------------------------- the site model

class Site:
    def __init__(self, data: dict, base: str, now: datetime | None = None):
        self.base = base if base.endswith("/") else base + "/"
        self.now = now or datetime.now(ROME)
        self.today = self.now.date()
        self.days = [self.today + timedelta(days=i) for i in range(7)]
        self.updated = data["updated"]
        self.films = data["films"]
        self.cinemas = data["cinemas"]
        # shows: [cinema, film, minutes since epoch, screen, label, format, booking url]
        self.shows = []
        for ci, fi, ts, screen, lab, fmt, url in data["shows"]:
            dt = datetime.fromtimestamp(ts * 60, ROME)
            if dt < self.now - timedelta(minutes=5):
                continue
            self.shows.append({"c": ci, "f": fi, "ts": ts, "dt": dt, "day": dt.date(), "time": dt.strftime("%H:%M"),
                               "screen": screen, "label": lab, "fmt": fmt, "url": url})
        self.shows.sort(key=lambda s: (s["ts"], s["c"]))
        self.week = [s for s in self.shows if s["day"] <= self.days[-1]]

        # cities, ordered by the number of screenings this week (then all)
        cnt = Counter(self.cinemas[s["c"]]["c"] for s in self.week)
        cnt_all = Counter(self.cinemas[s["c"]]["c"] for s in self.shows)
        self.cities = sorted(cnt_all, key=lambda c: (-cnt[c], -cnt_all[c], c))
        self.city_slug = {c: slug(c) for c in self.cities}

        # cinema slugs: name without generic words, unique inside its city
        used = defaultdict(set)
        for c in self.cinemas:
            s = slug(GENERIC.sub("", c["n"])) or slug(c["n"]) or "cinema"
            while s in used[c["c"]]:
                s += "-2"
            used[c["c"]].add(s)
            c["slug"] = s

    # urls
    def u(self, path: str = "") -> str:
        return self.base + path

    def city_url(self, city):
        return self.u(f"it/{self.city_slug[city]}/")

    def cinema_url(self, ci):
        c = self.cinemas[ci]
        return self.u(f"it/{self.city_slug.get(c['c'], slug(c['c']))}/{c['slug']}/")

    def film_url(self, fi):
        return self.u(f"it/film/{self.films[fi]['id']}/")

    def film_city_url(self, fi, city):
        return self.u(f"it/film/{self.films[fi]['id']}/{self.city_slug[city]}/")

    def poster_src(self, f, small=False):
        p = (f.get("ps") if small else None) or f.get("p") or ""
        return p if p.startswith("http") or not p else self.u(p)

    def city_of(self, s):
        return self.cinemas[s["c"]]["c"]


# ---------------------------------------------------------------- small components

def sub_h1(line1: str, line2: str = "", cite: bool = False, tag: str = "h1") -> str:
    """The subtitle box: yellow Arimo on a dark frame. Film titles go in <cite>."""
    l1 = f"<cite>{e(line1)}</cite>" if cite else e(line1)
    longest = max(len(line1), len(line2))
    size = "s" if longest > 24 else "m"
    inner = l1 + (f"<br>{e(line2)}" if line2 else "")
    return f'<div class="subbox"><{tag} class="subt subt-{size}">{inner}</{tag}></div>'


def chip(S: Site, s, film_title: str = "") -> str:
    c = S.cinemas[s["c"]]
    what = f"{film_title}, " if film_title else ""
    label = f"Prenota {what}{c['n']}, {long_date(s['day']).lower()} alle {s['time']} (sito del cinema)"
    return (f'<a class="chip" href="{e(s["url"])}" target="_blank" rel="noopener" data-t="{s["ts"]}" '
            f'aria-label="{e(label)}">{s["time"]}</a>')


def chips(S, shows, film_title="") -> str:
    return '<div class="chips">' + "".join(chip(S, s, film_title) for s in shows) + "</div>"


def poster(S: Site, f, cls="pos", small=True) -> str:
    src = S.poster_src(f, small)
    if src:
        # our own copies come in 120 and 480 px: let sharp screens take the bigger one
        srcset = ""
        if f.get("ps") and f.get("p") and not f["p"].startswith("http"):
            srcset = f' srcset="{e(S.u(f["ps"]))} 120w, {e(S.u(f["p"]))} 480w" sizes="{"100px" if small else "(min-width: 1024px) 180px, 33vw"}"'
        return f'<span class="{cls}"><img src="{e(src)}"{srcset} alt="" loading="lazy" decoding="async"><span class="ph" hidden>{e(f["t"])}</span></span>'
    return f'<span class="{cls} noimg"><span class="ph">{e(f["t"])}</span></span>'


def credit(f, with_ot=True) -> str:
    parts = []
    if with_ot and f.get("ot"):
        parts.append(e(f["ot"]))
    if f.get("y"):
        parts.append(str(f["y"]))
    if f.get("d"):
        parts.append(e(f["d"].split(",")[0].strip()))
    return " · ".join(parts)


def latlon(c) -> str:
    if c.get("lat") is None or c.get("lon") is None:
        return ""
    return f' data-lat="{c["lat"]:.5f}" data-lon="{c["lon"]:.5f}"'


def crumbs(S: Site, *items) -> str:
    out = [f'<a href="{S.u("it/")}">Home</a>']
    for label, href in items:
        out.append(f'<a href="{e(href)}">{e(label)}</a>' if href else f'<span aria-current="page">{e(label)}</span>')
    return '<nav class="crumbs" aria-label="Percorso">' + ' <span aria-hidden="true">›</span> '.join(out) + "</nav>"


ICON_SEARCH = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>'
ICON_PIN = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>'
ICON_EXT = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17L17 7"/><path d="M8 7h9v9"/></svg>'
ICON_NEXT = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>'


def page(S: Site, path: str, title: str, desc: str, body: str, crumbs_html: str = "") -> tuple[str, str]:
    css = S.u("assets/site.css")
    js = S.u("assets/site.js")
    fonts = "".join(f'<link rel="preload" href="{S.u("assets/fonts/" + f)}" as="font" type="font/woff2" crossorigin>'
                    for f in ("inter-latin-wght-normal.woff2", "arimo-latin-700-normal.woff2"))
    head = (
        '<!doctype html><html lang="it" class="nojs" data-base="' + e(S.base) + '"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        # Not launched yet: keep search engines and AI crawlers out (see also robots.txt)
        '<meta name="robots" content="noindex, nofollow, noarchive, nosnippet, noimageindex">'
        f"<title>{e(title)}</title><meta name=\"description\" content=\"{e(desc)}\">"
        '<meta name="theme-color" content="#FAFAF7">'
        f'{fonts}<link rel="stylesheet" href="{css}">'
        '<script>document.documentElement.className="js"</script>'
        f'<script src="{js}" defer></script></head><body>'
    )
    return path, head + header(S) + '<main id="main" class="wrap">' + crumbs_html + body + "</main>" + footer(S) + search_dialog() + "</body></html>"


def header(S: Site) -> str:
    return (
        '<a class="skip" href="#main">Vai al contenuto</a>'
        '<header class="hdr"><div class="hdr-in">'
        f'<a class="logo" href="{S.u("it/")}">{BRAND}<span class="dot" aria-hidden="true"></span></a>'
        '<nav class="topnav" aria-label="Sezioni">'
        f'<a href="{S.u("it/")}#citta">Città</a><a href="{S.u("it/film/")}">Film</a><a href="{S.u("it/cinema/")}">Cinema</a></nav>'
        f'<button type="button" class="icon-btn" data-search aria-label="Cerca un film, un cinema o una città">{ICON_SEARCH}</button>'
        "</div></header>"
    )


def footer(S: Site) -> str:
    cities = "".join(f'<a href="{S.city_url(c)}">{e(c)}</a>' for c in S.cities[:8])
    return (
        '<footer class="ftr"><div class="ftr-in">'
        f'<nav class="ftr-links" aria-label="Città">{cities}<a href="{S.u("it/cinema/")}">Tutte le città</a></nav>'
        '<nav class="ftr-links" aria-label="Informazioni">'
        f'<a href="{S.u("it/film/")}">Tutti i film</a>'
        f'<a href="mailto:{CONTACT}?subject=Segnalo%20un%20cinema">Segnala un cinema</a>'
        f'<a href="mailto:{CONTACT}">Contatti</a></nav>'
        '<p class="ftr-note">Orari aggiornati ogni notte dai siti dei cinema: controlla sempre sul sito del cinema prima di andare. '
        'Dati dei film da <a href="https://www.wikidata.org">Wikidata</a>. Mappe © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>.</p>'
        "</div></footer>"
    )


def search_dialog() -> str:
    return (
        '<dialog class="search" id="search" aria-label="Cerca">'
        '<form method="dialog" class="search-form" role="search">'
        '<label class="vh" for="q">Cerca un film, un cinema o una città</label>'
        '<input id="q" type="search" autocomplete="off" spellcheck="false" placeholder="Film, cinema o città" '
        'role="combobox" aria-expanded="false" aria-controls="results" aria-autocomplete="list">'
        '<button type="button" class="search-close" data-close>Chiudi</button></form>'
        '<div id="results" class="results" role="listbox" aria-label="Risultati"></div>'
        "</dialog>"
    )


def updated_line(S: Site) -> str:
    u = datetime.fromisoformat(S.updated)
    txt = f"Aggiornato il {u.day} {MONTHS[u.month - 1]} alle {u.strftime('%H:%M')} dai siti dei cinema"
    return f'<p class="upd" data-upd="{e(S.updated)}">{e(txt)}</p>'


def day_strip(S: Site, counts: dict, toggle: bool = False) -> str:
    btns = []
    for i, d in enumerate(S.days):
        n = counts.get(d, 0)
        top = "Oggi" if i == 0 else ("Domani" if i == 1 else WD_SHORT[d.weekday()])
        btns.append(
            f'<button type="button" class="day{"" if n else " empty"}" data-day="{d.isoformat()}" aria-pressed="false"'
            f'{"" if n else " disabled"} aria-label="{e(long_date(d))}: {plural(n, "proiezione", "proiezioni")}">'
            f'<span class="dw">{top}</span><span class="dn">{d.day}</span></button>')
    out = '<div class="strip" data-strip><div class="strip-in"><div class="days" role="group" aria-label="Scegli il giorno">' + "".join(btns) + "</div>"
    if toggle:
        out += ('<div class="toggle" role="group" aria-label="Vista">'
                '<button type="button" data-view="film" aria-pressed="true">Per film</button>'
                '<button type="button" data-view="cin" aria-pressed="false">Per cinema</button></div>')
    return out + "</div></div>"


def empty_day(S: Site, d: date, where: str) -> str:
    wd = "Oggi" if d == S.today else ("Domani" if d == S.today + timedelta(days=1) else WD[d.weekday()].capitalize())
    return (f'<div class="emptybox" data-empty hidden>{sub_h1(f"{wd} nessun film", f"in lingua originale {where}.", tag="p")}'
            '<button type="button" class="btn-y" data-goto>Vai al prossimo giorno</button></div>')


# ---------------------------------------------------------------- cards

def by_cinema(shows):
    g = defaultdict(list)
    for s in shows:
        g[s["c"]].append(s)
    return g


def by_film(shows):
    g = defaultdict(list)
    for s in shows:
        g[s["f"]].append(s)
    return g


def film_card(S: Site, fi, shows, city, compact=False) -> str:
    f = S.films[fi]
    href = S.film_city_url(fi, city)
    label = next((s["label"] for s in shows if s["label"]), "")
    rows = ""
    for ci, ss in sorted(by_cinema(shows).items(), key=lambda kv: kv[1][0]["ts"]):
        c = S.cinemas[ci]
        rows += (f'<div class="cinrow"{latlon(c)}><div class="row-top"><a class="row-name" href="{S.cinema_url(ci)}">{e(c["n"])}</a>'
                 f'<span class="dist" data-dist></span></div>{chips(S, ss, f["t"])}</div>')
    head = (f'<div class="fhead"><a class="pos-link" href="{href}" tabindex="-1" aria-hidden="true">{poster(S, f)}</a>'
            f'<div class="fmeta"><h3 class="ftitle"><a href="{href}">{e(f["t"])}</a></h3>'
            f'{"<p class=cred>" + credit(f) + "</p>" if credit(f) else ""}{badges(f, label)}</div></div>')
    more = f'<a class="more" href="{href}">Tutte le date a {e(city)}</a>'
    if not compact:
        return f'<article class="card film" data-card>{head}{rows}{more}</article>'
    line = " · ".join(f"<strong>{e(S.cinemas[ci]['n'])}</strong> <span class=tnum>{', '.join(s['time'] for s in ss)}</span>"
                      for ci, ss in sorted(by_cinema(shows).items(), key=lambda kv: kv[1][0]["ts"]))
    head_c = head.replace(f'<h3 class="ftitle"><a href="{href}">{e(f["t"])}</a></h3>', f'<h3 class="ftitle">{e(f["t"])}</h3>')
    head_c = re.sub(r'<a class="pos-link"[^>]*>(.*?)</a>', r"\1", head_c, count=1, flags=re.S)
    return (f'<details class="card film compact" data-card><summary>{head_c}<p class="oneline">{line}</p>'
            '<span class="btn-o">Mostra orari e prenota</span></summary>'
            f'{rows}{more}</details>')


def film_rows(S: Site, shows, city) -> str:
    """Films at one cinema: title, language, showtimes."""
    out = ""
    for fi, ss in sorted(by_film(shows).items(), key=lambda kv: kv[1][0]["ts"]):
        f = S.films[fi]
        label = next((s["label"] for s in ss if s["label"]), "")
        out += (f'<div class="frow"><div class="row-top"><a class="row-name" href="{S.film_city_url(fi, city)}">{e(f["t"])}</a>'
                f'<span class="lang">{e(lang_text(f))}{" · " + e(label) if label else ""}</span></div>{chips(S, ss, f["t"])}</div>')
    return out


def cinema_card(S: Site, ci, shows) -> str:
    c = S.cinemas[ci]
    ext = (f'<a class="ext" href="{e(c["w"])}" target="_blank" rel="noopener">Programma completo sul sito del cinema{ICON_EXT}</a>'
           if c.get("w") else "")
    return (f'<article class="card cin" data-card{latlon(c)}><div class="cc-top"><h3 class="ctitle"><a href="{S.cinema_url(ci)}">{e(c["n"])}</a></h3>'
            f'<span class="area">{e(c.get("z") or "")}<span class="dist" data-dist></span></span></div>'
            f'{film_rows(S, shows, c["c"])}{ext}</article>')


def poster_tile(S: Site, fi, sub: str, href: str) -> str:
    f = S.films[fi]
    return (f'<a class="ptile" href="{href}">{poster(S, f, "pos pos-l", small=False)}'
            f'<span class="pt-title">{e(f["t"])}</span><span class="pt-sub">{e(sub)}</span></a>')


# ---------------------------------------------------------------- pages

def home(S: Site):
    city_counts = Counter(S.city_of(s) for s in S.week)
    city_links = "".join(f'<a class="pill" href="{S.city_url(c)}">{e(c)}</a>' for c in S.cities[:6])
    films = by_film(S.week)
    rank = sorted(films, key=lambda fi: (-len({S.city_of(s) for s in films[fi]}), -len(films[fi]), S.films[fi]["t"]))
    tiles = ""
    for fi in rank[:12]:
        cs = sorted({S.city_of(s) for s in films[fi]})
        tiles += poster_tile(S, fi, lang_badge(S.films[fi]) + " · " + (cs[0] if len(cs) == 1 else f"{len(cs)} città"), S.film_url(fi))
    body = (
        f'<section class="top">{sub_h1("Film in lingua originale,", "vicino a te.")}</section>'
        '<section class="near" data-near-home>'
        f'<button type="button" class="btn-y btn-big" data-locate>{ICON_PIN}Cerca vicino a me</button>'
        '<p class="hint">La posizione resta sul tuo dispositivo: non la salviamo e non la inviamo a nessuno.</p>'
        '<div class="near-out" data-near-out hidden></div></section>'
        f'<section class="sec" id="citta"><h2 class="h2s">Oppure scegli una città</h2><div class="pills">{city_links}'
        f'<a class="pill pill-plain" href="{S.u("it/cinema/")}">Tutte</a></div></section>'
        f'<section class="sec"><div class="sec-head"><h2 class="h2">In sala questa settimana</h2><span class="count">{plural(len(films), "film", "film")}</span></div>'
        f'<div class="ptiles">{tiles}</div><a class="btn-o btn-wide" href="{S.u("it/film/")}">Tutti i film in sala</a></section>'
    )
    n_cities = len(city_counts)
    return page(S, "it/index.html", "Film in lingua originale vicino a te: orari nei cinema italiani",
                f"Gli orari dei film in versione originale in {n_cities} città italiane, aggiornati ogni notte dai siti dei cinema.", body)


def city_page(S: Site, city):
    shows = [s for s in S.week if S.city_of(s) == city]
    per_day = defaultdict(list)
    for s in shows:
        per_day[s["day"]].append(s)
    counts = {d: len(v) for d, v in per_day.items()}
    today = per_day.get(S.today, [])
    if today:
        lead = (f'<strong>Oggi {plural(len({s["f"] for s in today}), "film", "film")} in {plural(len({s["c"] for s in today}), "cinema", "cinema")}.</strong> '
                f'Il primo inizia alle {today[0]["time"]}.')
    else:
        lead = f'<strong>Questa settimana {plural(len({s["f"] for s in shows}), "film", "film")} in {plural(len({s["c"] for s in shows}), "cinema", "cinema")}.</strong>'
    days = ""
    for d in S.days:
        ds = per_day.get(d, [])
        fl = sorted(by_film(ds).items(), key=lambda kv: (-len(kv[1]), kv[1][0]["ts"]))
        fcards = "".join(film_card(S, fi, ss, city, compact=len(fl) > 6 and i >= 3) for i, (fi, ss) in enumerate(fl))  # long days only
        ccards = "".join(cinema_card(S, ci, ss) for ci, ss in sorted(by_cinema(ds).items(), key=lambda kv: S.cinemas[kv[0]]["n"]))
        days += (f'<section class="dayblock" data-dayblock="{d.isoformat()}"><h2 class="dayh">{long_date(d)}'
                 f'<span class="dayn"> · {plural(len(ds), "proiezione", "proiezioni")}</span></h2>'
                 f'<div class="v-film">{fcards}</div><div class="v-cin">{ccards}</div>{empty_day(S, d, "a " + city)}</section>')
    cins = Counter(s["c"] for s in shows)
    cin_films = {ci: len({s["f"] for s in shows if s["c"] == ci}) for ci in cins}
    side = "".join(
        f'<a class="lrow" href="{S.cinema_url(ci)}"{latlon(S.cinemas[ci])}><span class="lr-main"><span class="lr-name">{e(S.cinemas[ci]["n"])}</span>'
        f'<span class="lr-sub">{e(S.cinemas[ci].get("z") or "")}<span class="dist" data-dist></span></span></span>'
        f'<span class="lr-n">{plural(cin_films[ci], "film", "film")}</span>{ICON_NEXT}</a>'
        for ci in sorted(cins, key=lambda ci: -cin_films[ci]))
    body = (
        f'<section class="top">{sub_h1("Film in lingua originale", "a " + city)}<p class="lead" data-lead>{lead}</p>{updated_line(S)}</section>'
        f'{day_strip(S, counts, toggle=True)}'
        f'<div class="cols"><div class="list" data-days data-where="a {e(city)}">{days}</div>'
        f'<aside class="side"><div class="side-in"><h2 class="h2">Cinema a {e(city)}</h2>'
        f'<button type="button" class="btn-o btn-wide" data-locate>{ICON_PIN}Ordina per distanza da me</button>'
        f'<div class="lrows" data-sort>{side}</div></div></aside></div>'
    )
    return page(S, f"it/{S.city_slug[city]}/index.html", f"Film in lingua originale a {city}: orari di oggi e della settimana",
                f"Tutti i film in versione originale nei cinema di {city}, giorno per giorno, con il link per prenotare.",
                body, crumbs(S, (city, None)))


def cinema_page(S: Site, ci):
    c = S.cinemas[ci]
    city = c["c"]
    shows_all = [s for s in S.shows if s["c"] == ci]
    shows = [s for s in shows_all if s["day"] <= S.days[-1]]
    per_day = defaultdict(list)
    for s in shows:
        per_day[s["day"]].append(s)
    langs = Counter(lang_badge(S.films[fi]) for fi in {s["f"] for s in shows} if lang_badge(S.films[fi]) not in ("Lingua originale", "Più lingue"))
    facts = (f'<dl class="facts"><div><dt>Questa settimana</dt><dd>{plural(len({s["f"] for s in shows}), "film", "film")} in lingua originale</dd></div>'
             + (f'<div><dt>Lingue più frequenti</dt><dd>{e(", ".join(l for l, _ in langs.most_common(2)))}</dd></div>' if langs else "")
             + "</dl>")
    where = " · ".join(x for x in (c.get("a"), c.get("z"), city) if x)
    mp = ""
    if c.get("lat") is not None:
        la, lo = c["lat"], c["lon"]
        bbox = f"{lo - 0.006:.5f},{la - 0.0035:.5f},{lo + 0.006:.5f},{la + 0.0035:.5f}"
        mp = (f'<div class="map"><iframe title="Mappa: {e(c["n"])}" loading="lazy" referrerpolicy="no-referrer" '
              f'src="https://www.openstreetmap.org/export/embed.html?bbox={bbox}&amp;layer=mapnik&amp;marker={la:.5f},{lo:.5f}"></iframe>'
              '<span class="map-credit">© OpenStreetMap contributors</span></div>')
    q = ", ".join(x for x in (c["n"], c.get("a"), city) if x)
    dest = f"{c['lat']:.5f},{c['lon']:.5f}" if c.get("lat") is not None else q
    from urllib.parse import quote
    btns = ('<div class="btn-row">'
            + (f'<a class="btn-o" href="{e(c["w"])}" target="_blank" rel="noopener">Sito del cinema{ICON_EXT}</a>' if c.get("w") else "")
            + f'<a class="btn-o" href="https://www.google.com/maps/dir/?api=1&amp;destination={quote(dest)}" target="_blank" rel="noopener">Indicazioni{ICON_EXT}</a></div>')
    days = ""
    for d in S.days:
        ds = per_day.get(d, [])
        days += (f'<section class="dayblock" data-dayblock="{d.isoformat()}"><h2 class="dayh">{long_date(d)}'
                 f'<span class="dayn"> · {plural(len(ds), "proiezione", "proiezioni")}</span></h2>'
                 f'<div class="card rows">{film_rows(S, ds, city)}</div>{empty_day(S, d, al(c["n"]))}</section>')
    later = ""
    if len(shows_all) > len(shows):
        nxt = shows_all[len(shows)]
        later = f'<p class="note">Dopo questa settimana: {e(S.films[nxt["f"]]["t"])}, {long_date(nxt["day"]).lower()}.</p>'
    ext = (f'<a class="ext" href="{e(c["w"])}" target="_blank" rel="noopener">Programma completo sul sito del cinema{ICON_EXT}</a>' if c.get("w") else "")
    # other cinemas nearby: by distance when we have coordinates, else same city
    others = [j for j in {s["c"] for s in S.week} if j != ci]
    me = (c.get("lat"), c.get("lon"))
    dist = {j: km(me, (S.cinemas[j].get("lat"), S.cinemas[j].get("lon"))) for j in others}
    near = sorted([j for j in others if (dist[j] is not None and dist[j] < 30) or (dist[j] is None and S.cinemas[j]["c"] == city)],
                  key=lambda j: (dist[j] if dist[j] is not None else 99, S.cinemas[j]["n"]))[:4]
    near_html = "".join(
        f'<a class="lrow" href="{S.cinema_url(j)}"><span class="lr-main"><span class="lr-name">{e(S.cinemas[j]["n"])}</span>'
        f'<span class="lr-sub">{e(S.cinemas[j]["c"] if S.cinemas[j]["c"] != city else (S.cinemas[j].get("z") or city))}</span></span>'
        f'<span class="lr-n">{fmt_km(dist[j]) if dist[j] is not None else ""}</span>{ICON_NEXT}</a>' for j in near)
    body = (
        f'<section class="top">{sub_h1("Film in lingua originale", al(c["n"]))}<p class="addr">{e(where)}</p></section>'
        f'<div class="cols"><div class="list">'
        f'{day_strip(S, {d: len(v) for d, v in per_day.items()})}'
        f'<div data-days data-where="{e(al(c["n"]))}">{days}</div>{later}{ext}</div>'
        f'<aside class="side"><div class="side-in">{facts}{mp}{btns}'
        + (f'<h2 class="h2">Altri cinema vicini</h2><div class="lrows">{near_html}</div>' if near_html else "")
        + f'<a class="more" href="{S.city_url(city)}">Tutti i film a {e(city)}</a></div></aside></div>'
    )
    return page(S, f"it/{S.city_slug[city]}/{c['slug']}/index.html",
                f"Film in lingua originale {al(c['n'])} ({city}): orari della settimana",
                f"I film in versione originale {al(c['n'])} di {city}, con gli orari della settimana e il link per prenotare.",
                body, crumbs(S, (city, S.city_url(city)), (c["n"], None)))


def fmt_km(d: float) -> str:
    return f"{round(d * 1000 / 50) * 50:.0f} m" if d < 1 else f"{d:.1f} km".replace(".", ",")


def film_head(S: Site, fi) -> str:
    f = S.films[fi]
    meta = " · ".join(x for x in (str(f["y"]) if f.get("y") else "", e(f["d"]) if f.get("d") else "", f"{f['rt']} min" if f.get("rt") else "") if x)
    return (f'<div class="fhero">{poster(S, f, "pos pos-l", small=False)}<div class="fmeta">'
            + (f'<p class="ot">{e(f["ot"])}</p>' if f.get("ot") else "")
            + (f'<p class="cred">{meta}</p>' if meta else "") + badges(f) + "</div></div>")


def film_city_page(S: Site, fi, city):
    f = S.films[fi]
    shows = [s for s in S.shows if s["f"] == fi and S.city_of(s) == city]
    per_day = defaultdict(list)
    for s in shows:
        per_day[s["day"]].append(s)
    days = ""
    for d, ds in sorted(per_day.items()):
        lbl = "Oggi" if d == S.today else ("Domani" if d == S.today + timedelta(days=1) else WD_SHORT[d.weekday()])
        rows = "".join(f'<div class="cinrow"{latlon(S.cinemas[ci])}><div class="row-top"><a class="row-name" href="{S.cinema_url(ci)}">{e(S.cinemas[ci]["n"])}</a>'
                       f'<span class="dist" data-dist></span></div>{chips(S, ss, f["t"])}</div>'
                       for ci, ss in sorted(by_cinema(ds).items(), key=lambda kv: kv[1][0]["ts"]))
        days += f'<section class="daylist" data-card><h2 class="dayh">{lbl} · {d.day} {MONTHS[d.month - 1]}</h2><div class="card rows">{rows}</div></section>'
    last = shows[-1]["day"]
    summary = (f'{plural(len(shows), "proiezione", "proiezioni")} in {plural(len({s["c"] for s in shows}), "cinema", "cinema")}, '
               + ("solo oggi" if last == S.today else f"fino a {WD[last.weekday()]} {last.day} {MONTHS[last.month - 1]}") + ".")
    other = Counter(S.city_of(s) for s in S.shows if s["f"] == fi and S.city_of(s) != city)
    other_html = "".join(f'<a class="pill" href="{S.film_city_url(fi, c)}">{e(c)} ({n})</a>' for c, n in other.most_common())
    more = by_film([s for s in S.week if S.city_of(s) == city and s["f"] != fi])
    more_ids = sorted(more, key=lambda j: -len(more[j]))[:6]
    tiles = "".join(poster_tile(S, j, lang_badge(S.films[j]), S.film_city_url(j, city)) for j in more_ids)
    body = (
        f'<section class="top">{sub_h1(f["t"], "in lingua originale a " + city, cite=True)}{film_head(S, fi)}'
        f'<p class="lead">{e(summary)}</p><a class="more" href="{S.film_url(fi)}">Scheda del film</a></section>'
        f'<div class="cols"><div class="list">{days}</div><aside class="side"><div class="side-in">'
        f'<button type="button" class="btn-o btn-wide" data-locate>{ICON_PIN}Ordina per distanza da me</button>'
        + (f'<h2 class="h2">Anche in altre città</h2><div class="pills">{other_html}</div>' if other_html else "")
        + "</div></aside></div>"
        + (f'<section class="sec"><h2 class="h2">Altri film in lingua originale a {e(city)}</h2><div class="ptiles">{tiles}</div></section>' if tiles else "")
    )
    return page(S, f"it/film/{f['id']}/{S.city_slug[city]}/index.html",
                f"{f['t']} in lingua originale a {city}: orari e cinema",
                f"Dove vedere {f['t']} in versione originale a {city}: tutti i cinema e gli orari, con il link per prenotare.",
                body, crumbs(S, (city, S.city_url(city)), (f["t"], None)))


def film_page(S: Site, fi):
    f = S.films[fi]
    shows = [s for s in S.shows if s["f"] == fi]
    per_city = defaultdict(list)
    for s in shows:
        per_city[S.city_of(s)].append(s)
    rows = "".join(
        f'<a class="lrow" href="{S.film_city_url(fi, c)}"><span class="lr-main"><span class="lr-name">{e(c)}</span>'
        f'<span class="lr-sub">{plural(len({s["c"] for s in ss}), "cinema", "cinema")} · {plural(len(ss), "proiezione", "proiezioni")} · '
        f'la prossima {e(next_when(S, ss[0]))}</span></span>{ICON_NEXT}</a>'
        for c, ss in sorted(per_city.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    plot = ""
    if f.get("in"):
        src = (f'<a href="https://it.wikipedia.org/wiki/{e(f["wp"].replace(" ", "_"))}">Wikipedia</a> (CC BY-SA)' if f.get("wp") else "Wikipedia (CC BY-SA)")
        plot = f'<section class="sec"><h2 class="h2">Il film</h2><p class="plot">{e(f["in"])}</p><p class="src">Fonte: {src}</p></section>'
    elif f.get("o"):
        plot = f'<section class="sec"><h2 class="h2">Trama</h2><p class="plot">{e(f["o"])}</p><p class="src">Testo dal sito del cinema</p></section>'
    data = [("Regia", f.get("d")), ("Anno", f.get("y")), ("Durata", f"{f['rt']} min" if f.get("rt") else ""), ("Genere", f.get("g"))]
    dl = "".join(f"<div><dt>{k}</dt><dd>{e(v)}</dd></div>" for k, v in data if v)
    facts = (f'<dl class="facts">{dl}</dl>' + ('<p class="src">Dati: <a href="https://www.wikidata.org/wiki/' + e(f["wd"]) + '">Wikidata</a></p>' if f.get("wd") else "")) if dl else ""
    body = (
        f'<section class="top">{sub_h1(f["t"], "in lingua originale", cite=True)}{film_head(S, fi)}</section>'
        f'<div class="cols"><div class="list">'
        f'<section class="sec near" data-near-film="{e(f["id"])}"><h2 class="h2">Il più vicino a te</h2>'
        f'<button type="button" class="btn-y btn-big" data-locate>{ICON_PIN}Cerca vicino a me</button>'
        '<div class="near-out" data-near-out hidden></div></section>'
        f'<section class="sec"><h2 class="h2">Dove vederlo in lingua originale</h2><div class="lrows">{rows}</div></section>'
        f'{plot}</div><aside class="side"><div class="side-in">{facts}</div></aside></div>'
    )
    return page(S, f"it/film/{f['id']}/index.html", f"{f['t']} in lingua originale: dove vederlo in Italia",
                f"In quali cinema italiani vedere {f['t']} in versione originale, città per città.",
                body, crumbs(S, ("Film", S.u("it/film/")), (f["t"], None)))


def next_when(S: Site, s) -> str:
    d = s["day"]
    if d == S.today:
        return f"oggi alle {s['time']}"
    if d == S.today + timedelta(days=1):
        return f"domani alle {s['time']}"
    return f"{WD[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def film_hub(S: Site):
    films = by_film(S.shows)
    cities_of = {fi: sorted({S.city_of(s) for s in ss}, key=lambda c: S.cities.index(c)) for fi, ss in films.items()}
    multi = sorted([fi for fi in films if len(cities_of[fi]) > 1], key=lambda fi: (-len(cities_of[fi]), S.films[fi]["t"]))
    single = sorted([fi for fi in films if len(cities_of[fi]) == 1], key=lambda fi: slug(S.films[fi]["t"]))

    def row(fi, sub, href):
        f = S.films[fi]
        return (f'<a class="lrow lrow-f" href="{href}">{poster(S, f, "pos pos-xs")}<span class="lr-main"><span class="lr-name">{e(f["t"])}</span>'
                f'<span class="lr-sub">{e(lang_text(f))} · {e(sub)}</span></span>{ICON_NEXT}</a>')
    m = "".join(row(fi, ", ".join(cities_of[fi][:3]) + (f" +{len(cities_of[fi]) - 3}" if len(cities_of[fi]) > 3 else ""), S.film_url(fi)) for fi in multi)
    srows = []
    for i, fi in enumerate(single):
        c = cities_of[fi][0]
        cins = {s["c"] for s in films[fi]}
        where = S.cinemas[next(iter(cins))]["n"] if len(cins) == 1 else plural(len(cins), "cinema", "cinema")
        r = row(fi, f"{c} · {where}", S.film_city_url(fi, c))
        srows.append(r if i < 30 else r.replace('class="lrow lrow-f"', 'class="lrow lrow-f" data-extra hidden', 1))
    btn = (f'<button type="button" class="btn-o btn-wide" data-more>Mostra altri {len(single) - 30} film</button>' if len(single) > 30 else "")
    city_pills = "".join(f'<a class="pill" href="{S.city_url(c)}">{e(c)}</a>' for c in S.cities[:8])
    body = (
        f'<section class="top">{sub_h1("Film in lingua originale", "in Italia")}'
        f'<p class="lead"><strong>{plural(len(films), "film", "film")} in programmazione</strong> in {plural(len(S.cities), "città", "città")}.</p></section>'
        f'<section class="sec"><h2 class="h2s">Per città</h2><div class="pills">{city_pills}</div></section>'
        + (f'<section class="sec"><div class="sec-head"><h2 class="h2">In più città</h2><span class="count">{len(multi)}</span></div><div class="lrows">{m}</div></section>' if m else "")
        + f'<section class="sec"><div class="sec-head"><h2 class="h2">In una sola città</h2><span class="count">{len(single)}</span></div><div class="lrows">{"".join(srows)}</div>{btn}</section>'
    )
    return page(S, "it/film/index.html", "Tutti i film in lingua originale nei cinema italiani",
                "Tutti i film in versione originale in programmazione nei cinema italiani, e in quali città.", body, crumbs(S, ("Film", None)))


def cinema_hub(S: Site):
    cins = by_cinema(S.week)
    per_city = defaultdict(list)
    for ci in cins:
        per_city[S.cinemas[ci]["c"]].append(ci)

    def row(ci, show_city=False):
        c = S.cinemas[ci]
        n = len({s["f"] for s in cins[ci]})
        sub = " · ".join(x for x in ((c["c"] if show_city else c.get("z")), plural(n, "film", "film") + " questa settimana") if x)
        return (f'<a class="lrow" href="{S.cinema_url(ci)}"{latlon(c)}><span class="lr-main"><span class="lr-name">{e(c["n"])}</span>'
                f'<span class="lr-sub">{e(sub)}<span class="dist" data-dist></span></span></span>{ICON_NEXT}</a>')
    big = sorted([c for c in per_city if len(per_city[c]) > 1], key=lambda c: (-len(per_city[c]), c))
    small = sorted([ci for c in per_city if len(per_city[c]) == 1 for ci in per_city[c]], key=lambda ci: (S.cinemas[ci]["c"], S.cinemas[ci]["n"]))
    secs = "".join(
        f'<section class="sec"><div class="sec-head"><h2 class="h2"><a href="{S.city_url(c)}">{e(c)}</a></h2><span class="count">{plural(len(per_city[c]), "cinema", "cinema")}</span></div>'
        f'<div class="lrows" data-sort>{"".join(row(ci) for ci in sorted(per_city[c], key=lambda ci: S.cinemas[ci]["n"]))}</div></section>' for c in big)
    if small:
        secs += (f'<section class="sec"><div class="sec-head"><h2 class="h2">Altre città</h2><span class="count">un cinema ciascuna</span></div>'
                 f'<div class="lrows" data-sort>{"".join(row(ci, True) for ci in small)}</div></section>')
    body = (
        f'<section class="top">{sub_h1("Cinema con film", "in lingua originale")}'
        f'<p class="lead"><strong>{plural(len(cins), "cinema", "cinema")} in {plural(len(per_city), "città", "città")}</strong> questa settimana.</p>'
        f'<button type="button" class="btn-o" data-locate>{ICON_PIN}Ordina per distanza da me</button></section>{secs}'
    )
    return page(S, "it/cinema/index.html", "Cinema con film in lingua originale in Italia",
                "Tutti i cinema italiani che proiettano film in versione originale, città per città.", body, crumbs(S, ("Cinema", None)))


def not_found(S: Site):
    body = (f'<section class="top">{sub_h1("Questa pagina", "non esiste.")}'
            '<p class="lead">Forse il film non è più in programmazione. Cerca un altro film o scegli una città.</p>'
            f'<div class="pills">' + "".join(f'<a class="pill" href="{S.city_url(c)}">{e(c)}</a>' for c in S.cities[:6])
            + f'</div><a class="btn-y btn-wide" href="{S.u("it/")}">Vai alla home</a></section>')
    return page(S, "404.html", "Pagina non trovata", "Pagina non trovata.", body)


def root_redirect(S: Site) -> str:
    """/ goes to /it/. Old links of the one-page site (#f-film~city, #c-city, #s-cinema) are sent to the new pages."""
    return ('<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="robots" content="noindex">'
            f'<title>{BRAND}</title><meta http-equiv="refresh" content="1;url={S.u("it/")}">'
            "<script>(function(){var b=" + json.dumps(S.base) + ",h=location.hash.slice(1),m;"
            "if((m=h.match(/^f-([^~]+)(?:~(.+))?$/)))location.replace(b+'it/film/'+m[1]+'/'+(m[2]?m[2]+'/':''));"
            "else if((m=h.match(/^c-(.+)$/)))location.replace(b+'it/'+m[1]+'/');"
            "else location.replace(b+'it/');})()</script></head>"
            f'<body><a href="{S.u("it/")}">Vai al sito</a></body></html>')


def data_json(S: Site) -> str:
    """Small file for search and 'near me': cities, cinemas, films, upcoming screenings."""
    used_c = sorted({s["c"] for s in S.shows})
    used_f = sorted({s["f"] for s in S.shows})
    cmap = {ci: i for i, ci in enumerate(used_c)}
    fmap = {fi: i for i, fi in enumerate(used_f)}
    cities = S.cities
    out = {
        "updated": S.updated,
        "cities": [[c, S.city_slug[c]] for c in cities],
        "cinemas": [[S.cinemas[ci]["n"], cities.index(S.cinemas[ci]["c"]), S.cinemas[ci]["slug"], S.cinemas[ci].get("z") or "",
                     S.cinemas[ci].get("lat"), S.cinemas[ci].get("lon")] for ci in used_c],
        "films": [[S.films[fi]["t"], S.films[fi].get("ot") or "", " ".join(S.films[fi].get("al") or []), S.films[fi].get("y") or "",
                   S.films[fi].get("d") or "", lang_text(S.films[fi]), S.films[fi]["id"], S.poster_src(S.films[fi], small=True)] for fi in used_f],
        "shows": [[cmap[s["c"]], fmap[s["f"]], s["ts"], s["url"]] for s in S.shows],
    }
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def build(data: dict, out: Path, base: str = "/", now: datetime | None = None) -> dict:
    S = Site(data, base, now)
    pages = [home(S), film_hub(S), cinema_hub(S), not_found(S)]
    for c in S.cities:  # every city with screenings, also when none falls in the next 7 days
        pages.append(city_page(S, c))
    for ci in sorted({s["c"] for s in S.shows}):
        pages.append(cinema_page(S, ci))
    for fi in sorted({s["f"] for s in S.shows}):
        pages.append(film_page(S, fi))
        for c in sorted({S.city_of(s) for s in S.shows if s["f"] == fi}):
            pages.append(film_city_page(S, fi, c))
    for path, html in pages:
        p = out / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
    (out / "index.html").write_text(root_redirect(S), encoding="utf-8")
    (out / "it" / "data.json").write_text(data_json(S), encoding="utf-8")
    shutil.copytree(HERE / "assets", out / "assets", dirs_exist_ok=True)
    return {"pages": len(pages), "cities": len(S.cities), "cinemas": len({s["c"] for s in S.shows}), "films": len({s["f"] for s in S.shows})}
