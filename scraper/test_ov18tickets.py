"""Fixture tests for the 18tickets parser. Run: python -m pytest -q"""
from ov18tickets import parse_storefront_html, parse_film_page, is_ov, clean_title, subtitle_info

FIXTURE = """
<html><body>
<h4>VERSIONE ORIGINALE</h4>
<div class="row"><div class="col">
  <h6><a class="movie__title" href="/film/115813">DIGGER - V. O.</a></h6>
</div>
  <div class="movie__images"><a class="movie__title" href="/film/115813"><img class="img-fluid img-thumbnail" src="https://cdn.18tickets.net/ccb/uploads/film/playbill/115813/standard_x.jpg"></a></div>
  <span class="film-label">V.O.S.</span>
  <p class="movie__option"><strong>Director:</strong> Alejandro G. Iñárritu</p>
  <p class="movie__option"><strong>Language:</strong> inglese con sottotitoli in italiano</p>
  <a data-time="1792437000000" href="https://rialto.ccb.18tickets.it/film/115813/919e9ea6-e0c8-4a88-881b-047bb01826a9#theater-init"><ul><li>21:10 Rialto 2</li></ul></a>
  <a data-time="1792523400000" href="https://rialto.ccb.18tickets.it/film/115813/7b64b4a4-d335-4214-b413-296d543efe09#theater-init"><ul><li>21:10 Rialto 2</li></ul></a>
</div>
<div class="row"><div class="col">
  <h6><a class="movie__title" href="/film/999">FILM DOPPIATO</a></h6>
</div>
  <p class="movie__option"><strong>Language:</strong> Versione con doppiaggio italiano</p>
  <a data-time="1792437000000" href="https://odeon.ccb.18tickets.it/film/999/aaaa#theater-init"><ul><li>21:10 Odeon A</li></ul></a>
</div>
<!-- same film repeated in another homepage section: must be deduped -->
<div class="row"><div class="col">
  <h6><a class="movie__title" href="/film/115813">DIGGER - V. O.</a></h6>
</div>
  <span class="film-label">V.O.S.</span>
  <p class="movie__option"><strong>Language:</strong> inglese con sottotitoli in italiano</p>
  <a data-time="1792437000000" href="https://rialto.ccb.18tickets.it/film/115813/919e9ea6-e0c8-4a88-881b-047bb01826a9#theater-init"><ul><li>21:10 Rialto 2</li></ul></a>
</div>
</body></html>
"""


def test_parse_fixture():
    shows = parse_storefront_html(FIXTURE, "ccb.18tickets.it")
    assert len(shows) == 3  # 2 Digger (deduped) + 1 dubbed
    ov = [s for s in shows if s.is_ov]
    assert len(ov) == 2
    s = ov[0]
    assert s.cinema == "Rialto Studios" and s.city == "Bologna"
    assert s.title == "DIGGER"
    assert s.screen == "Rialto 2"
    assert s.date == "2026-10-19" and s.time == "21:10"
    assert s.booking_url.startswith("https://rialto.ccb.18tickets.it/film/115813/")
    assert s.subtitles == "sub IT"
    assert s.film_url == "https://ccb.18tickets.it/film/115813"
    assert s.poster.endswith("/115813/standard_x.jpg")
    assert s.director == "Alejandro G. Iñárritu"


FILM_PAGE = """
<html><head>
<meta property="og:description" content="Short version">
<meta property="og:image" content="https://cdn.18tickets.net/ccb/uploads/film/playbill/115813/standard_x.jpg">
</head><body>
<p class="movie__option"><strong>Genre:</strong> Commedia</p>
<p class="movie__option"><strong>Director:</strong> Alejandro G. Iñárritu</p>
<p class="movie__option"><strong>Year:</strong> 2026</p>
<div class="collapse"><div class="card-body">L'uomo più potente del mondo intraprende una missione disperata.</div></div>
</body></html>
"""


def test_film_page():
    info = parse_film_page(FILM_PAGE, "https://ccb.18tickets.it/film/115813")
    assert info["year"] == 2026
    assert info["director"] == "Alejandro G. Iñárritu"
    assert info["genre"] == "Commedia"
    assert info["synopsis"].startswith("L'uomo più potente")
    assert info["poster"].endswith("standard_x.jpg")


def test_is_ov_rules():
    assert is_ov("X", "", "Versione con doppiaggio italiano")[0] is False
    assert is_ov("X - V.O.S.", "", "")[0] is True
    assert is_ov("X - ORIGINAL LANGUAGE", "", "")[0] is True
    assert is_ov("X", "VOS", "")[0] is True
    assert is_ov("X", "", "Russo")[0] is True
    assert is_ov("X", "", "originale sottotitolato")[0] is True
    assert is_ov("X", "", "Italiano")[0] is False
    assert is_ov("X", "", "MUTO")[0] is False
    assert is_ov("X", "", "")[0] is False


def test_clean_title():
    assert clean_title("DIGGER - V. O.") == "DIGGER"
    assert clean_title("FATHERLAND - V.O.S.") == "FATHERLAND"
    assert clean_title("PRIMETIME - ORIGINAL LANGUAGE") == "PRIMETIME"
    assert clean_title("NAZA - ORIGINAL VERSION") == "NAZA"
    assert clean_title("ORIGINAL VERSION: THE INVITE") == "THE INVITE"
    assert clean_title("DUNE - PARTE TRE | 70MM - V.O.S.") == "DUNE - PARTE TRE | 70MM"


def test_subtitles():
    assert subtitle_info("Versione originale con sottotitoli in italiano e inglese") == "sub IT+EN"
    assert subtitle_info("Coreano con sottotitoli in Inglese") == "sub EN"
    assert subtitle_info("Russo") == ""
