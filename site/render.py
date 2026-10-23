"""
Static pages for the site, following claude/url-structure.md and claude/design-decisions.md.
Two languages with the same pages; the words live in i18n.py.

    /it/  /en/                                    home: near me, cities, films this week
    /it/roma/  /en/rome/                          city: 7-day strip, by film or by cinema
    /it/roma/<cinema>/  /en/rome/<cinema>/        cinema (same slug in both languages)
    /it/film/  /en/film/                          all films on now
    /it/film/<film>/  /en/film/<film>/            film: every city where it's on (Italian / English title)
    /it/film/<film>/roma/  /en/film/<film>/rome/  film x city: every screening, by day
    /it/cinema/  /en/cinema/                      all cinemas, grouped by city
    /it/data.json  /en/data.json                  small data file for search and "near me"

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
from urllib.parse import quote
from zoneinfo import ZoneInfo

from i18n import CITY_EN, JS, LANG_EN, MONTHS, T, WD, WD_SHORT, WORDS

ROME = ZoneInfo("Europe/Rome")
HERE = Path(__file__).parent
BRAND = "linguaoriginale"
CONTACT = "ciao@linguaoriginale.com"
GENERIC = re.compile(r"^(pop up cinema|cinema teatro|cineteatro|multicinema|multisala|multiplex|cinema|sala)\s+", re.I)
SUB_SHORT = {"sott. ITA": "IT", "sott. ENG": "EN", "sott. ITA + ENG": "IT+EN"}


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


def al(name: str) -> str:
    """Italian preposition before a cinema name: al Nuovo Olimpia, all'Arlecchino, alla Sala Cervi."""
    low = name.lower()
    if low.startswith(("sala ", "multisala ")):
        return "alla " + name
    if low[:1] in "aeiouàèéìòù":
        return "all'" + name
    return "al " + name


def unique_ids(titles: list[str], years: list) -> list[str]:
    used, out = set(), []
    for t, y in zip(titles, years):
        fid = slug(t) or "film"
        if fid in used and y:
            fid = f"{fid}-{y}"
        while fid in used:
            fid += "-2"
        used.add(fid)
        out.append(fid)
    return out


# ---------------------------------------------------------------- the site model, one per language

class Site:
    def __init__(self, data: dict, base: str, lang: str = "it", now: datetime | None = None):
        self.L = lang
        self.T = T[lang]
        self.base = base if base.endswith("/") else base + "/"
        self.now = now or datetime.now(ROME)
        self.today = self.now.date()
        self.days = [self.today + timedelta(days=i) for i in range(7)]
        self.updated = data["updated"]
        self.films = data["films"]
        self.cinemas = data["cinemas"]
        self.other: Site | None = None
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
        self.city_slug = {c: slug(self.cn(c)) for c in self.cities}

        # cinema slugs: name without generic words, unique inside its city (same in both languages)
        used = defaultdict(set)
        for c in self.cinemas:
            if "slug" in c:
                continue
            s = slug(GENERIC.sub("", c["n"])) or slug(c["n"]) or "cinema"
            while s in used[c["c"]]:
                s += "-2"
            used[c["c"]].add(s)
            c["slug"] = s
        # film slugs: Italian title under /it/ (built by build_data), English title under /en/
        if lang == "en":
            self.fid = unique_ids([self.ft(i) for i in range(len(self.films))], [f.get("y") for f in self.films])
        else:
            self.fid = [f["id"] for f in self.films]

    # words
    def t(self, key, **kw):
        s = self.T[key]
        return s.format(**kw) if kw else s

    def n(self, n: int, word: str) -> str:
        one, many = WORDS[self.L][word]
        return f"{n} {one if n == 1 else many}"

    def cn(self, city: str) -> str:
        return CITY_EN.get(city, city) if self.L == "en" else city

    def ft(self, fi) -> str:
        f = self.films[fi]
        if self.L == "en":
            ot = f.get("ot") or ""
            latin = ot and all(ord(ch) < 0x250 or not ch.isalpha() for ch in ot)  # not "가능한 사랑" as an English title
            return f.get("te") or (ot if latin else "") or f["t"]
        return f["t"]

    def in_city(self, city) -> str:
        return self.t("in_city", city=self.cn(city))

    def at(self, ci) -> str:
        name = self.cinemas[ci]["n"]
        return al(name) if self.L == "it" else self.t("at", name=name)

    def long_date(self, d: date) -> str:
        w = WD[self.L][d.weekday()]
        return f"{w[:1].upper() + w[1:]} {d.day} {MONTHS[self.L][d.month - 1]}"

    def mid_date(self, d: date) -> str:  # inside a sentence: "giovedì 29 ottobre" / "Thursday 29 October"
        return f"{WD[self.L][d.weekday()]} {d.day} {MONTHS[self.L][d.month - 1]}"

    def short_date(self, d: date) -> str:
        i = (d - self.today).days
        top = self.t("today") if i == 0 else (self.t("tomorrow") if i == 1 else WD_SHORT[self.L][d.weekday()])
        return f"{top} · {d.day} {MONTHS[self.L][d.month - 1]}"

    def next_when(self, s) -> str:
        d = s["day"]
        if d == self.today:
            return self.t("today_at", time=s["time"])
        if d == self.today + timedelta(days=1):
            return self.t("tomorrow_at", time=s["time"])
        return self.mid_date(d)

    # languages and badges
    def lang_badge(self, f) -> str:
        l = (f.get("l") or "").strip()
        if not l or l.lower() == "lingua originale":
            return self.t("orig_lang")
        parts = [p.strip() for p in re.split(r",|\s+e\s+", l) if p.strip()]
        if self.L == "en":
            parts = [LANG_EN.get(re.sub(r"^lingua\s+", "", p.lower()), p[:1].upper() + p[1:]) for p in parts]
        if len(parts) > 2:
            return self.t("many_langs")
        if len(parts) == 2:
            second = parts[1] if self.L == "en" else parts[1].lower()
            return f"{parts[0][:1].upper() + parts[0][1:]} {self.t('and')} {second}"
        return parts[0][:1].upper() + parts[0][1:]

    def sub_short(self, f) -> str:
        return SUB_SHORT.get(f.get("s") or "", "")

    def lang_text(self, f) -> str:
        s = self.sub_short(f)
        return self.lang_badge(f) + (", " + self.t("subs_inline", s=s) if s else "")

    def badges(self, f, label: str = "") -> str:
        out = [f'<span class="b b-lang">{e(self.lang_badge(f))}</span>']
        if self.sub_short(f):
            out.append(f'<span class="b b-sub">{e(self.t("subs", s=self.sub_short(f)))}</span>')
        if label:
            out.append(f'<span class="b b-lab">{e(label)}</span>')
        return '<span class="badges">' + "".join(out) + "</span>"

    # urls
    def u(self, path: str = "") -> str:
        return self.base + path

    def home_url(self):
        return self.u(f"{self.L}/")

    def city_url(self, city):
        return self.u(f"{self.L}/{self.city_slug[city]}/")

    def cinema_url(self, ci):
        c = self.cinemas[ci]
        return self.u(f"{self.L}/{self.city_slug.get(c['c'], slug(self.cn(c['c'])))}/{c['slug']}/")

    def film_url(self, fi):
        return self.u(f"{self.L}/film/{self.fid[fi]}/")

    def film_city_url(self, fi, city):
        return self.u(f"{self.L}/film/{self.fid[fi]}/{self.city_slug[city]}/")

    def films_url(self):
        return self.u(f"{self.L}/film/")

    def cinemas_url(self):
        return self.u(f"{self.L}/cinema/")

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
    # 26 characters still fit at full size on a 390px phone ("Film in lingua originale," = 25)
    size = "l" if longest > 40 else ("s" if longest > 26 else "m")
    inner = l1 + (f"<br>{e(line2)}" if line2 else "")
    return f'<div class="subbox"><{tag} class="subt subt-{size}">{inner}</{tag}></div>'


def chip(S: Site, s, film_title: str = "") -> str:
    c = S.cinemas[s["c"]]
    label = S.t("book", what=f"{film_title}, " if film_title else "", cinema=c["n"], date=S.mid_date(s["day"]), time=s["time"])
    return (f'<a class="chip" href="{e(s["url"])}" target="_blank" rel="noopener" data-t="{s["ts"]}" '
            f'aria-label="{e(label)}">{s["time"]}</a>')


def chips(S, shows, film_title="") -> str:
    return '<div class="chips">' + "".join(chip(S, s, film_title) for s in shows) + "</div>"


def poster(S: Site, fi, cls="pos", small=True) -> str:
    f = S.films[fi]
    title = S.ft(fi)
    src = S.poster_src(f, small)
    if src:
        # our own copies come in 120 and 480 px: let sharp screens take the bigger one
        srcset = ""
        if f.get("ps") and f.get("p") and not f["p"].startswith("http"):
            srcset = f' srcset="{e(S.u(f["ps"]))} 120w, {e(S.u(f["p"]))} 480w" sizes="{"100px" if small else "(min-width: 1024px) 180px, 33vw"}"'
        return f'<span class="{cls}"><img src="{e(src)}"{srcset} alt="" loading="lazy" decoding="async"><span class="ph" hidden>{e(title)}</span></span>'
    return f'<span class="{cls} noimg"><span class="ph">{e(title)}</span></span>'


def other_title(S: Site, fi) -> str:
    """The second title under the main one: original title (it) or Italian/original title (en)."""
    f = S.films[fi]
    main = S.ft(fi).lower()
    for t in ([f.get("ot")] if S.L == "it" else [f.get("ot"), f["t"]]):
        if t and t.lower() != main:
            return t
    return ""


def credit(S: Site, fi) -> str:
    f = S.films[fi]
    parts = [e(x) for x in (other_title(S, fi),) if x]
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
    out = [f'<a href="{S.home_url()}">{S.t("home")}</a>']
    for label, href in items:
        out.append(f'<a href="{e(href)}">{e(label)}</a>' if href else f'<span aria-current="page">{e(label)}</span>')
    return f'<nav class="crumbs" aria-label="{"Percorso" if S.L == "it" else "Breadcrumb"}">' + ' <span aria-hidden="true">›</span> '.join(out) + "</nav>"


ICON_SEARCH = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>'
ICON_PIN = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>'
ICON_EXT = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17L17 7"/><path d="M8 7h9v9"/></svg>'
ICON_NEXT = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>'


def page(S: Site, path: str, title: str, desc: str, body: str, crumbs_html: str = "", alt: str = "") -> tuple[str, str]:
    """alt: the same page in the other language (for hreflang and the IT/EN switch)."""
    css, js = S.u("assets/site.css"), S.u("assets/site.js")
    fonts = "".join(f'<link rel="preload" href="{S.u("assets/fonts/" + f)}" as="font" type="font/woff2" crossorigin>'
                    for f in ("inter-latin-wght-normal.woff2", "arimo-latin-700-normal.woff2"))
    me = S.u(path.removesuffix("index.html"))
    alts = ""
    if alt:
        it_url, en_url = (me, alt) if S.L == "it" else (alt, me)
        alts = (f'<link rel="alternate" hreflang="it" href="{e(it_url)}"><link rel="alternate" hreflang="en" href="{e(en_url)}">'
                f'<link rel="alternate" hreflang="x-default" href="{e(it_url)}">')
    head = (
        f'<!doctype html><html lang="{S.L}" class="nojs" data-base="{e(S.base)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        # Not launched yet: keep search engines and AI crawlers out (see also robots.txt)
        '<meta name="robots" content="noindex, nofollow, noarchive, nosnippet, noimageindex">'
        f'<title>{e(title)}</title><meta name="description" content="{e(desc)}">{alts}'
        '<meta name="theme-color" content="#FAFAF7">'
        f'{fonts}<link rel="stylesheet" href="{css}">'
        '<script>document.documentElement.className="js"</script>'
        f'<script type="application/json" id="l10n">{json.dumps(JS[S.L], ensure_ascii=False)}</script>'
        f'<script src="{js}" defer></script></head><body>'
    )
    return path, head + header(S, alt) + '<main id="main" class="wrap">' + crumbs_html + body + "</main>" + footer(S) + search_dialog(S) + "</body></html>"


def header(S: Site, alt: str) -> str:
    switch = (f'<a class="lang" href="{e(alt)}" hreflang="{S.other.L}" lang="{S.other.L}" aria-label="{e(S.t("switch_label"))}">{S.t("switch")}</a>'
              if alt else "")
    return (
        f'<a class="skip" href="#main">{S.t("skip")}</a>'
        '<header class="hdr"><div class="hdr-in">'
        f'<a class="logo" href="{S.home_url()}">{BRAND}<span class="dot" aria-hidden="true"></span></a>'
        f'<nav class="topnav" aria-label="{"Sezioni" if S.L == "it" else "Sections"}">'
        f'<a href="{S.home_url()}#citta">{S.t("nav_cities")}</a><a href="{S.films_url()}">{S.t("nav_films")}</a>'
        f'<a href="{S.cinemas_url()}">{S.t("nav_cinemas")}</a></nav>{switch}'
        f'<button type="button" class="icon-btn" data-search aria-label="{e(S.t("search_label"))}">{ICON_SEARCH}</button>'
        "</div></header>"
    )


def footer(S: Site) -> str:
    cities = "".join(f'<a href="{S.city_url(c)}">{e(S.cn(c))}</a>' for c in S.cities[:8])
    note = S.t("ftr_note", wikidata='<a href="https://www.wikidata.org">Wikidata</a>',
               osm='<a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>')
    return (
        '<footer class="ftr"><div class="ftr-in">'
        f'<nav class="ftr-links" aria-label="{S.t("nav_cities")}">{cities}<a href="{S.cinemas_url()}">{S.t("all_cities")}</a></nav>'
        '<nav class="ftr-links" aria-label="Info">'
        f'<a href="{S.films_url()}">{S.t("all_films")}</a>'
        f'<a href="mailto:{CONTACT}?subject={quote(S.t("suggest_subject"))}">{S.t("suggest")}</a>'
        f'<a href="mailto:{CONTACT}">{S.t("contact")}</a></nav>'
        f'<p class="ftr-note">{note}</p>'
        "</div></footer>"
    )


def search_dialog(S: Site) -> str:
    return (
        f'<dialog class="search" id="search" aria-label="{e(S.t("search_label"))}">'
        '<form method="dialog" class="search-form" role="search">'
        f'<label class="vh" for="q">{e(S.t("search_label"))}</label>'
        f'<input id="q" type="search" autocomplete="off" spellcheck="false" placeholder="{e(S.t("search_ph"))}" '
        'role="combobox" aria-expanded="false" aria-controls="results" aria-autocomplete="list">'
        f'<button type="button" class="search-close" data-close>{S.t("close")}</button></form>'
        '<div id="results" class="results" role="listbox"></div>'
        "</dialog>"
    )


def updated_line(S: Site) -> str:
    u = datetime.fromisoformat(S.updated)
    txt = S.t("updated", day=u.day, month=MONTHS[S.L][u.month - 1], time=u.strftime("%H:%M"))
    return f'<p class="upd" data-upd="{e(S.updated)}">{e(txt)}</p>'


def day_strip(S: Site, counts: dict, toggle: bool = False) -> str:
    btns = []
    for i, d in enumerate(S.days):
        n = counts.get(d, 0)
        # "Tomorrow" does not fit a day button on phones: English shows the weekday
        top = S.t("today") if i == 0 else (S.t("tomorrow") if i == 1 and S.L == "it" else WD_SHORT[S.L][d.weekday()])
        btns.append(
            f'<button type="button" class="day{"" if n else " empty"}" data-day="{d.isoformat()}" aria-pressed="false"'
            f'{"" if n else " disabled"} aria-label="{e(S.long_date(d))}: {S.n(n, "show")}">'
            f'<span class="dw">{top}</span><span class="dn">{d.day}</span></button>')
    out = f'<div class="strip" data-strip><div class="strip-in"><div class="days" role="group" aria-label="{S.t("pick_day")}">' + "".join(btns) + "</div>"
    if toggle:
        out += (f'<div class="toggle" role="group" aria-label="{S.t("view")}">'
                f'<button type="button" data-view="film" aria-pressed="true">{S.t("by_film")}</button>'
                f'<button type="button" data-view="cin" aria-pressed="false">{S.t("by_cinema")}</button></div>')
    return out + "</div></div>"


def empty_day(S: Site, d: date, where: str) -> str:
    """Filled in again by site.js for the day actually picked; this text is for pages read without it."""
    i = (d - S.today).days
    if S.L == "it":
        wd = S.t("today") if i == 0 else (S.t("tomorrow") if i == 1 else WD["it"][d.weekday()].capitalize())
        l1, l2 = S.t("empty_l1", day=wd), S.t("empty_l2", where=where)
    else:
        wd = "today" if i == 0 else ("tomorrow" if i == 1 else "on " + WD["en"][d.weekday()])
        l1, l2 = S.t("empty_l1"), S.t("empty_l2", where=where, day=wd)
    return (f'<div class="emptybox" data-empty hidden>{sub_h1(l1, l2, tag="p")}'
            f'<button type="button" class="btn-y" data-goto>{S.t("next_day")}</button></div>')


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
    title = S.ft(fi)
    href = S.film_city_url(fi, city)
    label = next((s["label"] for s in shows if s["label"]), "")
    rows = ""
    for ci, ss in sorted(by_cinema(shows).items(), key=lambda kv: kv[1][0]["ts"]):
        c = S.cinemas[ci]
        rows += (f'<div class="cinrow"{latlon(c)}><div class="row-top"><a class="row-name" href="{S.cinema_url(ci)}">{e(c["n"])}</a>'
                 f'<span class="dist" data-dist></span></div>{chips(S, ss, title)}</div>')
    cr = credit(S, fi)
    meta = f'{"<p class=cred>" + cr + "</p>" if cr else ""}{S.badges(f, label)}'
    more = f'<a class="more" href="{href}">{e(S.t("all_dates", where=S.in_city(city)))}</a>'
    if not compact:
        head = (f'<div class="fhead"><a class="pos-link" href="{href}" tabindex="-1" aria-hidden="true">{poster(S, fi)}</a>'
                f'<div class="fmeta"><h3 class="ftitle"><a href="{href}">{e(title)}</a></h3>{meta}</div></div>')
        return f'<article class="card film" data-card>{head}{rows}{more}</article>'
    line = " · ".join(f"<strong>{e(S.cinemas[ci]['n'])}</strong> <span class=tnum>{', '.join(s['time'] for s in ss)}</span>"
                      for ci, ss in sorted(by_cinema(shows).items(), key=lambda kv: kv[1][0]["ts"]))
    head = f'<div class="fhead">{poster(S, fi)}<div class="fmeta"><h3 class="ftitle">{e(title)}</h3>{meta}</div></div>'
    return (f'<details class="card film compact" data-card><summary>{head}<p class="oneline">{line}</p>'
            f'<span class="btn-o">{S.t("show_times")}</span></summary>{rows}{more}</details>')


def film_rows(S: Site, shows, city) -> str:
    """Films at one cinema: title, language, showtimes."""
    out = ""
    for fi, ss in sorted(by_film(shows).items(), key=lambda kv: kv[1][0]["ts"]):
        f = S.films[fi]
        label = next((s["label"] for s in ss if s["label"]), "")
        out += (f'<div class="frow"><div class="row-top"><a class="row-name" href="{S.film_city_url(fi, city)}">{e(S.ft(fi))}</a>'
                f'<span class="lang">{e(S.lang_text(f))}{" · " + e(label) if label else ""}</span></div>{chips(S, ss, S.ft(fi))}</div>')
    return out


def ext_link(S: Site, c) -> str:
    return (f'<a class="ext" href="{e(c["w"])}" target="_blank" rel="noopener">{S.t("full_programme")}{ICON_EXT}</a>' if c.get("w") else "")


def cinema_card(S: Site, ci, shows) -> str:
    c = S.cinemas[ci]
    return (f'<article class="card cin" data-card{latlon(c)}><div class="cc-top"><h3 class="ctitle"><a href="{S.cinema_url(ci)}">{e(c["n"])}</a></h3>'
            f'<span class="area">{e(c.get("z") or "")}<span class="dist" data-dist></span></span></div>'
            f'{film_rows(S, shows, c["c"])}{ext_link(S, c)}</article>')


def poster_tile(S: Site, fi, sub: str, href: str) -> str:
    return (f'<a class="ptile" href="{href}">{poster(S, fi, "pos pos-l", small=False)}'
            f'<span class="pt-title">{e(S.ft(fi))}</span><span class="pt-sub">{e(sub)}</span></a>')


def lrow(href: str, name: str, sub: str = "", right: str = "", attrs: str = "", lead: str = "", cls: str = "lrow") -> str:
    return (f'<a class="{cls}" href="{href}"{attrs}>{lead}<span class="lr-main"><span class="lr-name">{e(name)}</span>'
            f'<span class="lr-sub">{sub}</span></span>' + (f'<span class="lr-n">{e(right)}</span>' if right else "") + f"{ICON_NEXT}</a>")


def fmt_km(d: float, lang: str) -> str:
    return f"{round(d * 1000 / 50) * 50:.0f} m" if d < 1 else (f"{d:.1f} km".replace(".", ",") if lang == "it" else f"{d:.1f} km")


# ---------------------------------------------------------------- pages

def home(S: Site):
    city_links = "".join(f'<a class="pill" href="{S.city_url(c)}">{e(S.cn(c))}</a>' for c in S.cities[:8])
    films = by_film(S.week)
    rank = sorted(films, key=lambda fi: (-len({S.city_of(s) for s in films[fi]}), -len(films[fi]), S.ft(fi)))
    tiles = ""
    for fi in rank[:12]:
        cs = sorted({S.city_of(s) for s in films[fi]})
        tiles += poster_tile(S, fi, S.lang_badge(S.films[fi]) + " · " + (S.cn(cs[0]) if len(cs) == 1 else S.n(len(cs), "city")), S.film_url(fi))
    h1 = S.t("h1_home")
    body = (
        f'<div class="hero2"><div class="hero-main"><section class="top">{sub_h1(*h1)}</section>'
        '<section class="near" data-near-home>'
        f'<button type="button" class="btn-y btn-big" data-locate>{ICON_PIN}{S.t("near_btn")}</button>'
        f'<p class="hint">{S.t("near_hint")}</p>'
        '<div class="near-out" data-near-out hidden></div></section></div>'
        f'<section class="sec hero-side" id="citta"><h2 class="h2s">{S.t("or_city")}</h2><div class="pills">{city_links}'
        f'<a class="pill pill-plain" href="{S.cinemas_url()}">{S.t("all")}</a></div></section></div>'
        f'<section class="sec"><div class="sec-head"><h2 class="h2">{S.t("this_week")}</h2><span class="count">{S.n(len(films), "film")}</span></div>'
        f'<div class="ptiles">{tiles}</div><a class="btn-o btn-wide" href="{S.films_url()}">{S.t("all_on")}</a></section>'
    )
    n_cities = len({S.city_of(s) for s in S.week})
    return page(S, f"{S.L}/index.html", S.t("home_title"), S.t("home_desc", n=n_cities), body, alt=S.other.home_url())


def city_page(S: Site, city):
    shows = [s for s in S.week if S.city_of(s) == city]
    per_day = defaultdict(list)
    for s in shows:
        per_day[s["day"]].append(s)
    counts = {d: len(v) for d, v in per_day.items()}
    today = per_day.get(S.today, [])
    if today:
        lead = S.t("lead_today", films=S.n(len({s["f"] for s in today}), "film"), cinemas=S.n(len({s["c"] for s in today}), "cinema"), time=today[0]["time"])
    else:
        lead = S.t("lead_week", films=S.n(len({s["f"] for s in shows}), "film"), cinemas=S.n(len({s["c"] for s in shows}), "cinema"))
    where = S.in_city(city)
    days = ""
    for d in S.days:
        ds = per_day.get(d, [])
        fl = sorted(by_film(ds).items(), key=lambda kv: (-len(kv[1]), kv[1][0]["ts"]))
        fcards = "".join(film_card(S, fi, ss, city, compact=len(fl) > 6 and i >= 3) for i, (fi, ss) in enumerate(fl))  # long days only
        ccards = "".join(cinema_card(S, ci, ss) for ci, ss in sorted(by_cinema(ds).items(), key=lambda kv: S.cinemas[kv[0]]["n"]))
        days += (f'<section class="dayblock" data-dayblock="{d.isoformat()}"><h2 class="dayh">{S.long_date(d)}'
                 f'<span class="dayn"> · {S.n(len(ds), "show")}</span></h2>'
                 f'<div class="v-film">{fcards}</div><div class="v-cin">{ccards}</div>{empty_day(S, d, where)}</section>')
    cins = Counter(s["c"] for s in shows)
    cin_films = {ci: len({s["f"] for s in shows if s["c"] == ci}) for ci in cins}
    side = "".join(lrow(S.cinema_url(ci), S.cinemas[ci]["n"], e(S.cinemas[ci].get("z") or "") + '<span class="dist" data-dist></span>',
                        S.n(cin_films[ci], "film"), latlon(S.cinemas[ci])) for ci in sorted(cins, key=lambda ci: -cin_films[ci]))
    l1, l2 = S.t("h1_city")
    body = (
        f'<section class="top">{sub_h1(l1, l2.format(where=where))}<p class="lead" data-lead>{lead}</p>{updated_line(S)}</section>'
        f'{day_strip(S, counts, toggle=True)}'
        f'<div class="cols"><div class="list" data-days data-where="{e(where)}">{days}</div>'
        f'<aside class="side"><div class="side-in"><h2 class="h2">{e(S.t("cinemas_in", where=where))}</h2>'
        f'<button type="button" class="btn-o btn-wide" data-locate>{ICON_PIN}{S.t("sort_dist")}</button>'
        f'<div class="lrows" data-sort>{side}</div></div></aside></div>'
    )
    return page(S, f"{S.L}/{S.city_slug[city]}/index.html", S.t("city_title", city=S.cn(city)), S.t("city_desc", city=S.cn(city)),
                body, crumbs(S, (S.cn(city), None)), alt=S.other.city_url(city))


def cinema_page(S: Site, ci):
    c = S.cinemas[ci]
    city = c["c"]
    shows_all = [s for s in S.shows if s["c"] == ci]
    shows = [s for s in shows_all if s["day"] <= S.days[-1]]
    per_day = defaultdict(list)
    for s in shows:
        per_day[s["day"]].append(s)
    langs = Counter(S.lang_badge(S.films[fi]) for fi in {s["f"] for s in shows})
    for x in (S.t("orig_lang"), S.t("many_langs")):
        langs.pop(x, None)
    facts = (f'<dl class="facts"><div><dt>{S.t("f_week")}</dt><dd>{S.t("f_week_v", films=S.n(len({s["f"] for s in shows}), "film"))}</dd></div>'
             + (f'<div><dt>{S.t("f_langs")}</dt><dd>{e(", ".join(l for l, _ in langs.most_common(2)))}</dd></div>' if langs else "")
             + "</dl>")
    where = " · ".join(x for x in (c.get("a"), c.get("z"), S.cn(city)) if x)
    mp = ""
    if c.get("lat") is not None:
        la, lo = c["lat"], c["lon"]
        bbox = f"{lo - 0.006:.5f},{la - 0.0035:.5f},{lo + 0.006:.5f},{la + 0.0035:.5f}"
        mp = (f'<div class="map"><iframe title="{e(S.t("map", name=c["n"]))}" loading="lazy" referrerpolicy="no-referrer" '
              f'src="https://www.openstreetmap.org/export/embed.html?bbox={bbox}&amp;layer=mapnik&amp;marker={la:.5f},{lo:.5f}"></iframe>'
              '<span class="map-credit">© OpenStreetMap contributors</span></div>')
    dest = f"{c['lat']:.5f},{c['lon']:.5f}" if c.get("lat") is not None else ", ".join(x for x in (c["n"], c.get("a"), city) if x)
    btns = ('<div class="btn-row">'
            + (f'<a class="btn-o" href="{e(c["w"])}" target="_blank" rel="noopener">{S.t("website")}{ICON_EXT}</a>' if c.get("w") else "")
            + f'<a class="btn-o" href="https://www.google.com/maps/dir/?api=1&amp;destination={quote(dest)}" target="_blank" rel="noopener">{S.t("directions")}{ICON_EXT}</a></div>')
    at = S.at(ci)
    days = ""
    for d in S.days:
        ds = per_day.get(d, [])
        days += (f'<section class="dayblock" data-dayblock="{d.isoformat()}"><h2 class="dayh">{S.long_date(d)}'
                 f'<span class="dayn"> · {S.n(len(ds), "show")}</span></h2>'
                 f'<div class="card rows">{film_rows(S, ds, city)}</div>{empty_day(S, d, at)}</section>')
    later = ""
    if len(shows_all) > len(shows):
        nxt = shows_all[len(shows)]
        later = f'<p class="note">{e(S.t("after_week", film=S.ft(nxt["f"]), date=S.mid_date(nxt["day"])))}</p>'
    others = [j for j in {s["c"] for s in S.week} if j != ci]
    me = (c.get("lat"), c.get("lon"))
    dist = {j: km(me, (S.cinemas[j].get("lat"), S.cinemas[j].get("lon"))) for j in others}
    near = sorted([j for j in others if (dist[j] is not None and dist[j] < 30) or (dist[j] is None and S.cinemas[j]["c"] == city)],
                  key=lambda j: (dist[j] if dist[j] is not None else 99, S.cinemas[j]["n"]))[:4]
    near_html = "".join(lrow(S.cinema_url(j), S.cinemas[j]["n"],
                             e(S.cn(S.cinemas[j]["c"]) if S.cinemas[j]["c"] != city else (S.cinemas[j].get("z") or S.cn(city))),
                             fmt_km(dist[j], S.L) if dist[j] is not None else "") for j in near)
    l1, l2 = S.t("h1_cinema")
    body = (
        f'<section class="top">{sub_h1(l1, l2.format(at=at))}<p class="addr">{e(where)}</p></section>'
        f'<div class="cols"><div class="list">'
        f'{day_strip(S, {d: len(v) for d, v in per_day.items()})}'
        f'<div data-days data-where="{e(at)}">{days}</div>{later}{ext_link(S, c)}</div>'
        f'<aside class="side"><div class="side-in">{facts}{mp}{btns}'
        + (f'<h2 class="h2">{S.t("nearby")}</h2><div class="lrows">{near_html}</div>' if near_html else "")
        + f'<a class="more" href="{S.city_url(city)}">{e(S.t("all_in_city", where=S.in_city(city)))}</a></div></aside></div>'
    )
    return page(S, f"{S.L}/{S.city_slug[city]}/{c['slug']}/index.html", S.t("cinema_title", at=at, city=S.cn(city)),
                S.t("cinema_desc", at=at, city=S.cn(city)), body, crumbs(S, (S.cn(city), S.city_url(city)), (c["n"], None)),
                alt=S.other.cinema_url(ci))


def film_head(S: Site, fi) -> str:
    f = S.films[fi]
    meta = " · ".join(x for x in (str(f["y"]) if f.get("y") else "", e(f["d"]) if f.get("d") else "", f"{f['rt']} min" if f.get("rt") else "") if x)
    ot = other_title(S, fi)
    return (f'<div class="fhero">{poster(S, fi, "pos pos-l", small=False)}<div class="fmeta">'
            + (f'<p class="ot">{e(ot)}</p>' if ot else "")
            + (f'<p class="cred">{meta}</p>' if meta else "") + S.badges(f) + "</div></div>")


def film_city_page(S: Site, fi, city):
    title = S.ft(fi)
    shows = [s for s in S.shows if s["f"] == fi and S.city_of(s) == city]
    per_day = defaultdict(list)
    for s in shows:
        per_day[s["day"]].append(s)
    days = ""
    for d, ds in sorted(per_day.items()):
        rows = "".join(f'<div class="cinrow"{latlon(S.cinemas[ci])}><div class="row-top"><a class="row-name" href="{S.cinema_url(ci)}">{e(S.cinemas[ci]["n"])}</a>'
                       f'<span class="dist" data-dist></span></div>{chips(S, ss, title)}</div>'
                       for ci, ss in sorted(by_cinema(ds).items(), key=lambda kv: kv[1][0]["ts"]))
        days += f'<section class="daylist" data-card><h2 class="dayh">{S.short_date(d)}</h2><div class="card rows">{rows}</div></section>'
    last = shows[-1]["day"]
    summary = S.t("fc_summary", shows=S.n(len(shows), "show"), cinemas=S.n(len({s["c"] for s in shows}), "cinema"),
                  until=S.t("only_today") if last == S.today else S.t("until", date=S.mid_date(last)))
    other = Counter(S.city_of(s) for s in S.shows if s["f"] == fi and S.city_of(s) != city)
    other_html = "".join(f'<a class="pill" href="{S.film_city_url(fi, c)}">{e(S.cn(c))} ({n})</a>' for c, n in other.most_common())
    more = by_film([s for s in S.week if S.city_of(s) == city and s["f"] != fi])
    tiles = "".join(poster_tile(S, j, S.lang_badge(S.films[j]), S.film_city_url(j, city)) for j in sorted(more, key=lambda j: -len(more[j]))[:6])
    where = S.in_city(city)
    body = (
        f'<section class="top">{sub_h1(title, S.t("h1_film_city", where=where), cite=True)}{film_head(S, fi)}'
        f'<p class="lead">{e(summary)}</p><a class="more" href="{S.film_url(fi)}">{S.t("about_film")}</a></section>'
        f'<div class="cols"><div class="list">{days}</div><aside class="side"><div class="side-in">'
        f'<button type="button" class="btn-o btn-wide" data-locate>{ICON_PIN}{S.t("sort_dist")}</button>'
        + (f'<h2 class="h2">{S.t("other_cities")}</h2><div class="pills">{other_html}</div>' if other_html else "")
        + "</div></aside></div>"
        + (f'<section class="sec"><h2 class="h2">{e(S.t("more_in_city", where=where))}</h2><div class="ptiles">{tiles}</div></section>' if tiles else "")
    )
    return page(S, f"{S.L}/film/{S.fid[fi]}/{S.city_slug[city]}/index.html", S.t("fc_title", film=title, city=S.cn(city)),
                S.t("fc_desc", film=title, city=S.cn(city)), body, crumbs(S, (S.cn(city), S.city_url(city)), (title, None)),
                alt=S.other.film_city_url(fi, city))


def film_page(S: Site, fi):
    f = S.films[fi]
    title = S.ft(fi)
    shows = [s for s in S.shows if s["f"] == fi]
    per_city = defaultdict(list)
    for s in shows:
        per_city[S.city_of(s)].append(s)
    rows = "".join(
        lrow(S.film_city_url(fi, c), S.cn(c), e(f'{S.n(len({s["c"] for s in ss}), "cinema")} · {S.n(len(ss), "show")} · {S.t("next_one", when=S.next_when(ss[0]))}'))
        for c, ss in sorted(per_city.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    plot = ""
    intro, wiki, wp_host = (f.get("in"), f.get("wp"), "it") if S.L == "it" else (f.get("ien"), f.get("we"), "en")
    if intro:
        src = (f'<a href="https://{wp_host}.wikipedia.org/wiki/{e(quote(wiki.replace(" ", "_")))}">Wikipedia</a> (CC BY-SA)' if wiki else "Wikipedia (CC BY-SA)")
        plot = f'<section class="sec"><h2 class="h2">{S.t("the_film")}</h2><p class="plot">{e(intro)}</p><p class="src">{S.t("source")}: {src}</p></section>'
    elif f.get("o") and S.L == "it":  # the cinemas write in Italian: not used on English pages
        plot = f'<section class="sec"><h2 class="h2">{S.t("plot")}</h2><p class="plot">{e(f["o"])}</p><p class="src">{S.t("from_cinema")}</p></section>'
    data = [(S.t("d_director"), f.get("d")), (S.t("d_year"), f.get("y")), (S.t("d_runtime"), f"{f['rt']} min" if f.get("rt") else ""),
            (S.t("d_genre"), f.get("g") if S.L == "it" else "")]
    dl = "".join(f"<div><dt>{k}</dt><dd>{e(v)}</dd></div>" for k, v in data if v)
    facts = (f'<dl class="facts">{dl}</dl>' + (f'<p class="src">{S.t("data_from")}: <a href="https://www.wikidata.org/wiki/{e(f["wd"])}">Wikidata</a></p>' if f.get("wd") else "")) if dl else ""
    body = (
        f'<section class="top">{sub_h1(title, S.t("h1_film"), cite=True)}{film_head(S, fi)}</section>'
        f'<div class="cols"><div class="list">'
        f'<section class="sec near" data-near-film="{e(S.fid[fi])}"><h2 class="h2">{S.t("nearest")}</h2>'
        f'<button type="button" class="btn-y btn-big" data-locate>{ICON_PIN}{S.t("near_btn")}</button>'
        '<div class="near-out" data-near-out hidden></div></section>'
        f'<section class="sec"><h2 class="h2">{S.t("where_to_see")}</h2><div class="lrows">{rows}</div></section>'
        f'{plot}</div><aside class="side"><div class="side-in">{facts}</div></aside></div>'
    )
    return page(S, f"{S.L}/film/{S.fid[fi]}/index.html", S.t("film_title", film=title), S.t("film_desc", film=title),
                body, crumbs(S, (S.t("crumb_films"), S.films_url()), (title, None)), alt=S.other.film_url(fi))


def film_hub(S: Site):
    films = by_film(S.shows)
    cities_of = {fi: sorted({S.city_of(s) for s in ss}, key=lambda c: S.cities.index(c)) for fi, ss in films.items()}
    multi = sorted([fi for fi in films if len(cities_of[fi]) > 1], key=lambda fi: (-len(cities_of[fi]), S.ft(fi)))
    single = sorted([fi for fi in films if len(cities_of[fi]) == 1], key=lambda fi: slug(S.ft(fi)))

    def row(fi, sub, href, extra=False):
        return lrow(href, S.ft(fi), e(S.lang_text(S.films[fi])) + " · " + e(sub), lead=poster(S, fi, "pos pos-xs"),
                    cls="lrow lrow-f", attrs=" data-extra hidden" if extra else "")
    m = "".join(row(fi, ", ".join(S.cn(c) for c in cities_of[fi][:3]) + (f" +{len(cities_of[fi]) - 3}" if len(cities_of[fi]) > 3 else ""), S.film_url(fi)) for fi in multi)
    srows = []
    for i, fi in enumerate(single):
        c = cities_of[fi][0]
        cins = {s["c"] for s in films[fi]}
        where = S.cinemas[next(iter(cins))]["n"] if len(cins) == 1 else S.n(len(cins), "cinema")
        srows.append(row(fi, f"{S.cn(c)} · {where}", S.film_city_url(fi, c), extra=i >= 30))
    btn = (f'<button type="button" class="btn-o btn-wide" data-more>{S.t("show_more", n=len(single) - 30)}</button>' if len(single) > 30 else "")
    city_pills = "".join(f'<a class="pill" href="{S.city_url(c)}">{e(S.cn(c))}</a>' for c in S.cities[:8])
    body = (
        f'<div class="hero2"><div class="hero-main"><section class="top">{sub_h1(*S.t("h1_films"))}'
        f'<p class="lead">{S.t("films_lead", films=S.n(len(films), "film"), cities=S.n(len(S.cities), "city"))}</p></section></div>'
        f'<section class="sec hero-side"><h2 class="h2s">{S.t("by_city")}</h2><div class="pills">{city_pills}</div></section></div>'
        + (f'<section class="sec"><div class="sec-head"><h2 class="h2">{S.t("multi_city")}</h2><span class="count">{len(multi)}</span></div><div class="lrows">{m}</div></section>' if m else "")
        + f'<section class="sec"><div class="sec-head"><h2 class="h2">{S.t("one_city")}</h2><span class="count">{len(single)}</span></div><div class="lrows">{"".join(srows)}</div>{btn}</section>'
    )
    return page(S, f"{S.L}/film/index.html", S.t("films_title"), S.t("films_desc"), body, crumbs(S, (S.t("crumb_films"), None)), alt=S.other.films_url())


def cinema_hub(S: Site):
    cins = by_cinema(S.week)
    per_city = defaultdict(list)
    for ci in cins:
        per_city[S.cinemas[ci]["c"]].append(ci)

    def row(ci, show_city=False):
        c = S.cinemas[ci]
        n = len({s["f"] for s in cins[ci]})
        sub = " · ".join(x for x in ((S.cn(c["c"]) if show_city else c.get("z")), S.t("this_week_n", films=S.n(n, "film"))) if x)
        return lrow(S.cinema_url(ci), c["n"], e(sub) + '<span class="dist" data-dist></span>', attrs=latlon(c))
    big = sorted([c for c in per_city if len(per_city[c]) > 1], key=lambda c: (-len(per_city[c]), c))
    small = sorted([ci for c in per_city if len(per_city[c]) == 1 for ci in per_city[c]], key=lambda ci: (S.cn(S.cinemas[ci]["c"]), S.cinemas[ci]["n"]))
    secs = "".join(
        f'<section class="sec"><div class="sec-head"><h2 class="h2"><a href="{S.city_url(c)}">{e(S.cn(c))}</a></h2><span class="count">{S.n(len(per_city[c]), "cinema")}</span></div>'
        f'<div class="lrows" data-sort>{"".join(row(ci) for ci in sorted(per_city[c], key=lambda ci: S.cinemas[ci]["n"]))}</div></section>' for c in big)
    if small:
        secs += (f'<section class="sec"><div class="sec-head"><h2 class="h2">{S.t("other_towns")}</h2><span class="count">{S.t("one_each")}</span></div>'
                 f'<div class="lrows" data-sort>{"".join(row(ci, True) for ci in small)}</div></section>')
    body = (
        f'<div class="hero2"><div class="hero-main"><section class="top">{sub_h1(*S.t("h1_cinemas"))}'
        f'<p class="lead">{S.t("cinemas_lead", cinemas=S.n(len(cins), "cinema"), cities=S.n(len(per_city), "city"))}</p></section></div>'
        f'<div class="hero-side"><button type="button" class="btn-o btn-wide" data-locate>{ICON_PIN}{S.t("sort_dist")}</button></div></div>{secs}'
    )
    return page(S, f"{S.L}/cinema/index.html", S.t("cinemas_title"), S.t("cinemas_desc"), body, crumbs(S, (S.t("crumb_cinemas"), None)),
                alt=S.other.cinemas_url())


def not_found(S: Site):
    """One 404 page for the whole site (GitHub Pages serves 404.html): Italian, with the English line below."""
    E = S.other
    body = (f'<section class="top">{sub_h1(*S.t("h1_404"))}'
            f'<p class="lead">{S.t("lead_404")}</p><p class="lead" lang="en">{E.t("lead_404")}</p>'
            '<div class="pills">' + "".join(f'<a class="pill" href="{S.city_url(c)}">{e(c)}</a>' for c in S.cities[:6])
            + f'</div><div class="btn-row"><a class="btn-y" href="{S.home_url()}">{S.t("go_home")}</a>'
            f'<a class="btn-o" href="{E.home_url()}" lang="en">English</a></div></section>')
    return page(S, "404.html", "Pagina non trovata / Page not found", "Pagina non trovata.", body)


def root_redirect(S: Site) -> str:
    """/ goes to /it/ or /en/ by the browser language. Old links of the one-page site
    (#f-film~city, #c-city) are sent to the new Italian pages."""
    return ('<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="robots" content="noindex">'
            f'<title>{BRAND}</title><meta http-equiv="refresh" content="2;url={S.u("it/")}">'
            "<script>(function(){var b=" + json.dumps(S.base) + ",h=location.hash.slice(1),m;"
            "if((m=h.match(/^f-([^~]+)(?:~(.+))?$/)))return location.replace(b+'it/film/'+m[1]+'/'+(m[2]?m[2]+'/':''));"
            "if((m=h.match(/^c-(.+)$/)))return location.replace(b+'it/'+m[1]+'/');"
            "var l=(navigator.languages&&navigator.languages[0]||navigator.language||'it').toLowerCase();"
            "location.replace(b+(l.indexOf('it')===0?'it/':'en/'));})()</script></head>"
            f'<body><a href="{S.u("it/")}">Italiano</a> · <a href="{S.u("en/")}">English</a></body></html>')


def data_json(S: Site) -> str:
    """Small file for search and 'near me': cities, cinemas, films, upcoming screenings."""
    used_c = sorted({s["c"] for s in S.shows})
    used_f = sorted({s["f"] for s in S.shows})
    cmap = {ci: i for i, ci in enumerate(used_c)}
    fmap = {fi: i for i, fi in enumerate(used_f)}

    def words(fi):  # every title the film goes by, so both languages find it
        f = S.films[fi]
        return " ".join(x for x in {f["t"], f.get("ot") or "", f.get("te") or "", *(f.get("al") or [])} if x)
    out = {
        "updated": S.updated,
        "lang": S.L,
        "cities": [[S.cn(c), S.city_slug[c], c] for c in S.cities],
        "cinemas": [[S.cinemas[ci]["n"], S.cities.index(S.cinemas[ci]["c"]), S.cinemas[ci]["slug"], S.cinemas[ci].get("z") or "",
                     S.cinemas[ci].get("lat"), S.cinemas[ci].get("lon")] for ci in used_c],
        "films": [[S.ft(fi), "", words(fi), S.films[fi].get("y") or "", S.films[fi].get("d") or "", S.lang_text(S.films[fi]),
                   S.fid[fi], S.poster_src(S.films[fi], small=True)] for fi in used_f],
        "shows": [[cmap[s["c"]], fmap[s["f"]], s["ts"], s["url"]] for s in S.shows],
    }
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def build(data: dict, out: Path, base: str = "/", now: datetime | None = None) -> dict:
    it, en = Site(data, base, "it", now), Site(data, base, "en", now)
    it.other, en.other = en, it
    total = 0
    for S in (it, en):
        pages = [home(S), film_hub(S), cinema_hub(S)]
        pages += [city_page(S, c) for c in S.cities]  # every city with screenings, also when none falls in the next 7 days
        pages += [cinema_page(S, ci) for ci in sorted({s["c"] for s in S.shows})]
        for fi in sorted({s["f"] for s in S.shows}):
            pages.append(film_page(S, fi))
            pages += [film_city_page(S, fi, c) for c in sorted({S.city_of(s) for s in S.shows if s["f"] == fi})]
        if S is it:
            pages.append(not_found(S))
        for path, html in pages:
            p = out / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html, encoding="utf-8")
        (out / S.L / "data.json").write_text(data_json(S), encoding="utf-8")
        total += len(pages)
    (out / "index.html").write_text(root_redirect(it), encoding="utf-8")
    shutil.copytree(HERE / "assets", out / "assets", dirs_exist_ok=True)
    return {"pages": total, "cities": len(it.cities), "cinemas": len({s["c"] for s in it.shows}), "films": len({s["f"] for s in it.shows})}
