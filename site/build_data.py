"""Build the website (one HTML file) from data/ov_showtimes.csv.
Usage: python site/build_data.py --csv data/ov_showtimes.csv --out public
"""
import argparse, csv, json, re, unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ap = argparse.ArgumentParser()
ap.add_argument('--csv', default='data/ov_showtimes.csv')
ap.add_argument('--out', default='public')
ap.add_argument('--data', default='data', help='folder with tmdb_cache.json (optional)')
args = ap.parse_args()
HERE = Path(__file__).parent
import sys; sys.path.insert(0, str(HERE))
from films import film_key, norm, strip_edition, LANG_IT

try:
    TMDB = json.loads((Path(args.data) / 'tmdb_cache.json').read_text(encoding='utf-8'))
except (FileNotFoundError, json.JSONDecodeError):
    TMDB = {}

def tmdb_for(raw):
    m = TMDB.get(film_key(raw))
    return m if m and m.get('id') else None

def short(text, n=480):
    text = (text or '').strip()
    if len(text) <= n: return text
    cut = text[:n].rsplit(' ', 1)[0].rstrip(',;:')
    return cut + '…'

rows = list(csv.DictReader(open(args.csv, encoding='utf-8')))

def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',s).strip('-')

SMALL = set("a e i o di da in con su per tra fra il lo la le gli un una uno del della dei delle al alla allo ai agli alle dal dalla nel nella sul sulla the of and a an in on at to for vs".split())
def tcase(t):
    t = t.lower()
    out = []
    words = t.split(' ')
    for i, w in enumerate(words):
        prev = words[i-1] if i else ''
        if i and w in SMALL and prev not in ('-', '–', ':') and not prev.endswith(':') and not w.startswith('('):
            out.append(w); continue
        # capitalise first letter (skip leading punctuation like ( or ")
        m = re.match(r'^([^a-zà-ÿ]*)(.)(.*)$', w)
        out.append(m.group(1)+m.group(2).upper()+m.group(3) if m else w)
    s = ' '.join(out)
    s = re.sub(r"\b(Ii|Iii|Iv)\b", lambda m: m.group(1).upper(), s)
    s = re.sub(r"\bVs\b", "vs", s).replace("La la Land", "La La Land")
    return s

ALIAS = {
 "I DIAVOLI (THE DEVILS)": "I DIAVOLI (THE DEVILS)", "I DIAVOLI": "I DIAVOLI (THE DEVILS)",
 "DUNE: PART THREE": "DUNE - PARTE TRE", "DUNE - PARTE TRE | 70MM": "DUNE - PARTE TRE",
 "WILDE HORSE NINE": "WILD HORSE NINE",
 "L'INFERNALE QUINLAN": "L'INFERNALE QUINLAN (TOUCH OF EVIL)",
 "L'INFERNALE QUINLAN (TOUCH OF EVIL) (ED.SPEC.)": "L'INFERNALE QUINLAN (TOUCH OF EVIL)",
 "THE ROCKY HORROR PICTURE SHOW (ED. SPEC.)": "THE ROCKY HORROR PICTURE SHOW",
 "THE INVITE - IL PIACERE E' TUTTO NOSTRO": "THE INVITE – IL PIACERE È TUTTO NOSTRO",
 "MINNIE & MOSKOWITZ (MINNIE AND MOSKOWITZ) (RIED.)": "MINNIE & MOSKOWITZ",
 "TRAINSPOTTING (RIED.)": "TRAINSPOTTING",
 "STRAY KIDS WORLD TOUR \"RUN IT\": - IL LIVE VIEWING": "STRAY KIDS WORLD TOUR \"RUN IT\" - IL LIVE VIEWING",
}
FORMAT = {"DUNE - PARTE TRE | 70MM": "70mm"}

def lang_short(lang):
    l = lang.strip()
    low = l.lower()
    base = re.split(r'\s+con\s+|,\s*sottotitol', low)[0].strip()
    if base in ('originale', 'versione originale', 'lingua originale', 'originale sottotitolato', 'originale sottotitolata', ''):
        base = 'lingua originale'
    base = base.replace('/', ', ').replace(' e ', ', ')
    m = re.search(r'sottotitol\w*(.*)$', low)
    sub = ''
    if m:
        a = m.group(1)
        it, en = 'italian' in a, 'ingles' in a
        sub = 'sott. ITA + ENG' if it and en else ('sott. ENG' if en else 'sott. ITA')
    if base == 'lingua originale' and 'originale sottotitolat' in low: sub = sub or 'sott. ITA'
    return base[:1].upper() + base[1:], sub

VENUE = {
 ("Roma","Nuovo Olimpia"): ("Via in Lucina 16/g", "Centro", "https://www.circuitocinema.com/cinema/nuovo-olimpia"),
 ("Roma","Quattro Fontane"): ("Via delle Quattro Fontane 23", "Barberini", "https://www.circuitocinema.com/cinema/quattro-fontane"),
 ("Roma","Giulio Cesare"): ("Viale Giulio Cesare 229", "Prati", "https://www.circuitocinema.com/cinema/giulio-cesare"),
 ("Roma","Eurcine"): ("Via Liszt 32", "EUR", "https://www.circuitocinema.com/cinema/eurcine"),
 ("Roma","Multisala Lux"): ("Via Massaciuccoli 31", "Africano", "https://www.cinemadiroma.it"),
 ("Roma","Odeon Multiscreen"): ("Piazza Stefano Jacini 22", "Vigna Stelluti", "https://www.cinemadiroma.it"),
 ("Roma","Cinema Intrastevere"): ("Vicolo Moroni 3/a", "Trastevere", "https://www.cinemadiroma.it"),
 ("Roma","Cinema Tibur"): ("Via degli Etruschi 36", "San Lorenzo", "https://www.cinemadiroma.it"),
 ("Bologna","Cinema Lumière"): ("Via Azzo Gardino 65", "Piazzetta Pasolini", "https://www.cinetecadibologna.it"),
 ("Bologna","Cinema Modernissimo"): ("Piazza Re Enzo 1", "Centro", "https://www.cinetecadibologna.it"),
 ("Bologna","Sala Cervi"): ("Via Riva di Reno 72", "Centro", "https://www.cinetecadibologna.it"),
 ("Bologna","Cinema Odeon"): ("Via Mascarella 3", "Zona universitaria", "https://www.circuitocinemabologna.it"),
 ("Bologna","Rialto Studios"): ("Via Rialto 19", "Centro", "https://www.circuitocinemabologna.it"),
 ("Bologna","Roma d'Essai"): ("Via Fondazza 4", "Centro", "https://www.circuitocinemabologna.it"),
 ("Bologna","Europa Cinema"): ("Via Pietralata 55/a", "Centro", "https://www.circuitocinemabologna.it"),
 ("Bologna","Pop Up Cinema Arlecchino"): ("Via Lame 59", "Centro", "https://www.popupcinema.it"),
 ("Bologna","Pop Up Cinema Jolly"): ("Via Marconi 14", "Centro", "https://www.popupcinema.it"),
 ("Bologna","Pop Up Cinema Medica"): ("Via Montegrappa 9", "Centro", "https://www.popupcinema.it"),
 ("Bologna","Pop Up Cinema Bristol"): ("Via Toscana 146", "Savena", "https://www.popupcinema.it"),
 ("Bologna","Cinema Fossolo"): ("Viale Abramo Lincoln 3", "Fossolo", "https://www.circuitocinema.com"),
 ("Firenze","Cinema Flora"): ("", "", ""), ("Firenze","Cinema Fiorella"): ("", "", ""),
 ("Napoli","Cinema Metropolitan"): ("", "", ""),
}
cities = {"Roma": {"en": "Rome"}, "Bologna": {"en": ""}, "Firenze": {"en": "Florence"}, "Napoli": {"en": "Naples"}}

cin_list = []; cin_idx = {}
for (city, name), (addr, area, web) in VENUE.items():
    cin_idx[(city, name)] = len(cin_list)
    cin_list.append({"id": slug(name), "n": name, "c": city, "a": addr, "z": area, "w": web})

film_list = []; film_idx = {}; shows = []
for r in rows:
    raw = r['title']
    m = tmdb_for(raw)
    # films are grouped by TMDB id when we have one, otherwise by the cleaned cinema title
    key = ('tmdb', m['id']) if m else ('title', film_key(ALIAS.get(raw, raw)))
    if key not in film_idx:
        film_idx[key] = len(film_list)
        if m:
            t = m['title'] or m['original_title']
            rec = {"t": t, "ot": m['original_title'] if norm(m.get('original_title') or '') != norm(t) else '',
                   "y": m.get('year'), "p": m.get('poster_path') or '', "o": short(m.get('overview')),
                   "tm": m['id'], "rt": m.get('runtime') or 0, "_ol": m.get('original_language')}
        else:
            rec = {"t": tcase(strip_edition(ALIAS.get(raw, raw)))}
        rec["al"] = []  # other titles used by the cinemas, for search
        film_list.append(rec)
    fi = film_idx[key]
    f = film_list[fi]
    lg, sb = lang_short(r['language'])
    if 'l' not in f: f['l'], f['s'], f['lr'] = lg, sb, r['language']
    if f['l'] == 'Lingua originale' and lg != 'Lingua originale': f['l'] = lg
    if not f['s'] and sb: f['s'] = sb
    alt = tcase(strip_edition(raw))
    if norm(alt) not in (norm(f['t']), norm(f.get('ot', ''))) and alt not in f['al']: f['al'].append(alt)
    if (r['city'], r['cinema']) not in cin_idx:  # venue not in VENUE yet: still show it
        cin_idx[(r['city'], r['cinema'])] = len(cin_list)
        cin_list.append({"id": slug(r['cinema']), "n": r['cinema'], "c": r['city'], "a": "", "z": "", "w": ""})
        cities.setdefault(r['city'], {"en": ""})
    ci = cin_idx[(r['city'], r['cinema'])]
    ts = int(datetime.fromisoformat(r['starts_at']).timestamp() // 60)
    lab = r['label'] if r['label'] and not re.fullmatch(r'v\.?o\.?s?\.?|vos|v\.o\. sott\.', r['label'], re.I) else ''
    screen = re.sub(r'\s+', ' ', r['screen']).strip()
    if screen.isdigit(): screen = 'Sala ' + screen
    fmt = FORMAT.get(raw, '')
    shows.append([ci, fi, ts, screen, tcase(lab) if lab else '', fmt, r['booking_url'].replace('https://','').replace('#theater-init','')])

shows.sort(key=lambda s: s[2])

# language from TMDB when the cinema only says "lingua originale"; stable unique page ids
used = set()
for f in film_list:
    ol = f.pop('_ol', None)
    if f['l'] == 'Lingua originale' and ol in LANG_IT and ol != 'it':
        f['l'] = LANG_IT[ol]
    fid = slug(f['t']) or 'film'
    if fid in used and f.get('y'): fid = f"{fid}-{f['y']}"
    while fid in used: fid += '-2'
    used.add(fid); f['id'] = fid
    if not f['al']: del f['al']
data = {"updated": datetime.now(ZoneInfo("Europe/Rome")).replace(microsecond=0).isoformat(), "cities": cities, "cinemas": cin_list, "films": film_list, "shows": shows,
        "missing": {"Roma": ["Barberini", "Troisi", "Greenwich", "Nuovo Sacher", "Farnese", "Nuovo Cinema Aquila"]}}
out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
html = (HERE / 'template.html').read_text(encoding='utf-8')
page = html.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
# GitHub Pages needs a full HTML document
doc = ('<!doctype html><html lang="it"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
       '<meta name="description" content="Tutti i film in versione originale nei cinema di Roma e Bologna, con orari e link per prenotare.">'
       '<style>:root{padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
       '</head><body>' + page + '</body></html>')
(out / 'index.html').write_text(doc, encoding='utf-8')
print(f"{len(film_list)} films, {len(shows)} shows -> {out / 'index.html'}")
