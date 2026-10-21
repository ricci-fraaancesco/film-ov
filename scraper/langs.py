"""Language codes used by ticketing platforms -> Italian names, and OV helpers."""
import re

CODES = {
    "EN": "Inglese", "ENG": "Inglese", "UK": "Inglese", "US": "Inglese",
    "IT": "Italiano", "ITA": "Italiano",
    "FR": "Francese", "FRA": "Francese", "FRE": "Francese",
    "DE": "Tedesco", "DEU": "Tedesco", "GER": "Tedesco", "TED": "Tedesco",
    "ES": "Spagnolo", "ESP": "Spagnolo", "SPA": "Spagnolo",
    "PT": "Portoghese", "POR": "Portoghese",
    "JA": "Giapponese", "JAP": "Giapponese", "JPN": "Giapponese", "GIA": "Giapponese",
    "KO": "Coreano", "KOR": "Coreano",
    "ZH": "Cinese", "CHI": "Cinese", "ZHO": "Cinese", "CIN": "Cinese",
    "RU": "Russo", "RUS": "Russo",
    "AR": "Arabo", "ARA": "Arabo",
    "HE": "Ebraico", "HEB": "Ebraico",
    "HI": "Hindi", "HIN": "Hindi",
    "TR": "Turco", "TUR": "Turco",
    "PL": "Polacco", "POL": "Polacco",
    "SV": "Svedese", "SWE": "Svedese",
    "DA": "Danese", "DAN": "Danese",
    "NO": "Norvegese", "NOR": "Norvegese",
    "NL": "Olandese", "NLD": "Olandese", "DUT": "Olandese",
    "EL": "Greco", "GRE": "Greco",
    "FA": "Persiano", "PER": "Persiano",
    "UKR": "Ucraino",
}
OV_WORDS = {"O.V.", "OV", "V.O.", "VO", "V.O.S.", "VOS", "V.O.S", "O.V", "V.O",
            "ORIGINAL VERSION", "ORIGINALVERSION", "LINGUA ORIGINALE", "VERSIONE ORIGINALE",
            "ORIGINALE", "SOTTOTITOLATO", "SUBTITLED"}


def lang_name(code: str) -> str:
    return CODES.get((code or "").strip().upper().rstrip("."), "")


def language_text(lang: str = "", subs: str = "", ov: bool = False) -> str:
    """Italian description in the same style as the 18tickets 'Language' field,
    e.g. 'Inglese con sottotitoli in italiano'."""
    name = lang_name(lang) if lang else ""
    if not name:
        name = "Lingua originale" if ov else ""
    sub_name = lang_name(subs)
    if sub_name:
        sub_txt = {"Italiano": "italiano", "Inglese": "inglese"}.get(sub_name, sub_name.lower())
        return f"{name or 'Lingua originale'} con sottotitoli in {sub_txt}"
    return name


def clean_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()
