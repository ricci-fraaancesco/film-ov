"""Shared helpers to normalise film titles (used by tmdb_match.py and build_data.py)."""
import re
import unicodedata

# Tags the cinemas add to a title that are not part of the film's name
EDITION_TAGS = re.compile(
    r"\s*\((ed\.?\s*spec\.?|ried\.?|restaurato|versione restaurata|director'?s cut|4k)\)\s*"
    r"|\s+(?:in\s+)?4k(?:\s+restaurato)?\s*$"  # "2001: Odissea nello spazio 4K"
    r"|\s*\|\s*70\s*mm\b|\s*-\s*70\s*mm\b"
    r"|\s*\((?:19|20)\d{2}\)\s*$"  # "Ragione E Sentimento (2026)" (Webtic)
    # original-version markers: "(Ov) Fatherland", "(O.V.) Ragione e sentimento", "Dune - V.O.", "Dune (VOS)"
    r"|^\s*\((?:o\.?\s?v\.?|v\.?\s?o\.?s?\.?)\)\s*"
    r"|\s*(?:[-–]\s*|\()(?:o\.?\s?v\.?|v\.?\s?o\.?s?\.?|versione originale|lingua originale|original version)\)?\s*$",
    re.I,
)

LANG_IT = {
    "en": "Inglese", "fr": "Francese", "de": "Tedesco", "es": "Spagnolo", "ja": "Giapponese",
    "ko": "Coreano", "ru": "Russo", "it": "Italiano", "pt": "Portoghese", "zh": "Cinese",
    "cn": "Cinese", "ar": "Arabo", "he": "Ebraico", "sv": "Svedese", "da": "Danese",
    "no": "Norvegese", "nb": "Norvegese", "pl": "Polacco", "ro": "Rumeno", "el": "Greco",
    "tr": "Turco", "hi": "Hindi", "fa": "Persiano", "nl": "Olandese", "fi": "Finlandese",
    "cs": "Ceco", "hu": "Ungherese", "uk": "Ucraino", "sr": "Serbo", "hr": "Croato",
    "bs": "Bosniaco", "ka": "Georgiano", "th": "Thai", "id": "Indonesiano", "ga": "Irlandese",
    "is": "Islandese", "et": "Estone", "lv": "Lettone", "lt": "Lituano", "sk": "Slovacco",
    "sl": "Sloveno", "bg": "Bulgaro", "mk": "Macedone", "sq": "Albanese", "hy": "Armeno",
    "ta": "Tamil", "te": "Telugu", "bn": "Bengalese", "ur": "Urdu", "vi": "Vietnamita",
    "tl": "Filippino", "ms": "Malese", "xx": "Muto",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


EXTRA_TAGS = re.compile(
    r"\s*\((?:[^()]*\b(?:ried|riedizione|rest|restaurat\w*|spec|4k)\b[^()]*)\)"  # "(RIED. 2026)", "(ED. REST. 4K)"
    r"|^\s*(?:vos|v\.o\.s?\.?|o\.v\.)\s+"  # "Vos Matrix", "V.O. Matrix"
    r"|\s+(?:v\.o\.s?\.?|o\.v\.)\s*$",  # "MATRIX 4K V.O."
    re.I)


def strip_edition(title: str) -> str:
    prev = None
    while prev != title:  # several tags can follow each other: "MATRIX 4K V.O."
        prev = title
        title = re.sub(r"\s+", " ", EXTRA_TAGS.sub(" ", EDITION_TAGS.sub(" ", title))).strip(" -–")
    return title


def film_key(title: str) -> str:
    """Stable key for a cinema title: 'DUNE - PARTE TRE | 70MM' and 'Dune - parte tre' give the same key."""
    return norm(strip_edition(title))


def query_variants(title: str) -> list[str]:
    """Titles to try on TMDB, best first.
    'PRANZO ALLE OTTO (DINNER AT EIGHT)' -> full, 'DINNER AT EIGHT', 'PRANZO ALLE OTTO'
    "L'AMORE BUGIARDO - GONE GIRL"      -> full, 'GONE GIRL', "L'AMORE BUGIARDO"
    """
    t = strip_edition(title)
    out = [t]
    m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", t)
    if m:
        out += [m.group(2), m.group(1)]
    if " - " in t or " – " in t:
        parts = [p.strip() for p in re.split(r"\s[-–]\s", t) if p.strip()]
        if len(parts) == 2:
            out += [parts[1], parts[0]]
    seen, res = set(), []
    for q in out:
        k = norm(q)
        if len(k) >= 2 and k not in seen:
            seen.add(k)
            res.append(q)
    return res
