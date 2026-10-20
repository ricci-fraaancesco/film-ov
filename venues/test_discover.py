"""Tests for the website / platform check (no network)."""
from collections import Counter

from discover import analyse, check, run, storefront_of

HOME = """<html><body>
<a href="/programmazione/">Programmazione</a>
<a href="/privacy">Privacy</a>
<a href="https://www.facebook.com/cinema">Facebook</a>
<a href="https://www.mymovies.it/cinema/roma/">MYmovies</a>
<a href="/contatti">Contatti</a>
</body></html>"""

PROG = """<html><body>
<h2>Digger</h2>
<a href="https://odeon.ccb.18tickets.it/film/115813/919e9ea6#theater-init">Acquista 21:10</a>
<script src="https://www.webtic.it/widget.js"></script>
</body></html>"""

STOREFRONT = """<html><body>
<div><div><h6><a class="movie__title" href="/film/115813">DIGGER - V. O.</a></h6></div>
<p class="movie__option"><strong>Language:</strong> inglese con sottotitoli in italiano</p>
<a data-time="1792437000000" href="https://odeon.ccb.18tickets.it/film/115813/919e9ea6#theater-init"><li>21:10 Odeon C</li></a>
</div></body></html>"""


class FakeFetch:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise ConnectionError("down")
        return url, self.pages[url]


def test_analyse_finds_platforms_and_pages():
    a = analyse(HOME, "https://www.cinemaodeon.it/")
    assert a["platforms"] == {} and a["pages"] == ["https://www.cinemaodeon.it/programmazione/"]
    b = analyse(PROG, "https://www.cinemaodeon.it/programmazione/")
    assert b["platforms"]["18tickets"].startswith("https://odeon.ccb.18tickets.it/film/")
    assert "webtic" in b["platforms"]


def test_unknown_booking_site():
    html = '<a href="https://tickets.miabiglietteria.it/acquista?id=4">Acquista i biglietti</a><a href="https://www.youtube.com/x">Trailer</a>'
    a = analyse(html, "https://cinema.example.it/")
    assert a["unknown"] == {"tickets.miabiglietteria.it": 1}


def test_storefront_of():
    assert storefront_of("https://odeon.ccb.18tickets.it/film/1/x") == ("ccb.18tickets.it", "odeon", "https://odeon.ccb.18tickets.it/")
    assert storefront_of("https://ccb.18tickets.it/") == ("ccb.18tickets.it", "", "https://ccb.18tickets.it/")


def test_check_activates_18tickets():
    f = FakeFetch({"https://www.cinemaodeon.it/": HOME,
                   "https://www.cinemaodeon.it/programmazione/": PROG,
                   "https://odeon.ccb.18tickets.it/": STOREFRONT})
    upd = check({"website": "https://www.cinemaodeon.it/"}, f)
    assert upd["status"] == "active" and upd["platform"] == "18tickets"
    assert upd["booking_url"] == "https://odeon.ccb.18tickets.it/" and "1 film" in upd["note"]


def test_check_other_cases():
    assert check({"website": ""}, FakeFetch({}))["status"] == "no_website"
    assert check({"website": "https://www.facebook.com/cinemax"}, FakeFetch({}))["status"] == "social_only"
    up = check({"website": "https://www.ucicinemas.it/cinema/lazio/roma/uci-cinemas-roma-est/"}, FakeFetch({}))
    assert up["status"] == "adapter_missing" and up["platform"] == "uci"
    assert check({"website": "cinemadown.it"}, FakeFetch({}))["status"] == "website_down"
    nothing = FakeFetch({"http://cinemavuoto.it": "<html><a href='/chi-siamo'>Chi siamo</a></html>"})
    assert check({"website": "cinemavuoto.it"}, nothing)["status"] == "no_booking_link"
    wt = FakeFetch({"https://cinemawt.it/": '<a href="https://www.webtic.it/#/shopping?action=loadLocal&localId=5013">Biglietti</a>'})
    up = check({"website": "https://cinemawt.it/"}, wt)
    assert up["status"] == "adapter_missing" and up["platform"] == "webtic" and "localId=5013" in up["booking_url"]


def test_run_order_and_no_website_queue():
    rows = [
        {"name": "A", "city": "X", "region": "Lazio", "sources": "osm", "website": "https://a.it/", "status": "to_check", "platform": "", "booking_url": "", "note": "", "last_checked": ""},
        {"name": "B", "city": "X", "region": "Lazio", "sources": "cinemarevolution", "website": "https://b.it/", "status": "to_check", "platform": "", "booking_url": "", "note": "", "last_checked": ""},
        {"name": "C", "city": "X", "region": "Lazio", "sources": "cinemarevolution", "website": "", "status": "to_check", "platform": "", "booking_url": "", "note": "", "last_checked": ""},
        {"name": "D", "city": "X", "region": "Lazio", "sources": "filmov", "website": "https://d.it/", "status": "active", "platform": "18tickets", "booking_url": "x", "note": "", "last_checked": ""},
    ]
    f = FakeFetch({"https://b.it/": "<html></html>"})
    counts = run(rows, f, batch=1, now="2026-10-20T00:00:00+00:00")
    assert f.calls == ["https://b.it/"]                      # confirmed cinema first, one per batch
    assert rows[1]["status"] == "no_booking_link" and rows[0]["status"] == "to_check"
    assert rows[2]["status"] == "no_website" and rows[3]["status"] == "active"
    assert counts == Counter({"no_booking_link": 1})


def test_group_storefront_needs_review():
    two = STOREFRONT + STOREFRONT.replace("odeon.ccb", "rialto.ccb").replace("115813", "115814")
    f = FakeFetch({"https://cinemabo.it/": '<a href="https://ccb.18tickets.it/">Acquista</a>', "https://ccb.18tickets.it/": two})
    up = check({"website": "https://cinemabo.it/"}, f)
    assert up["status"] == "needs_review" and "odeon" in up["note"] and "rialto" in up["note"]
    one = FakeFetch({"https://cinemabo.it/": '<a href="https://ccb.18tickets.it/">Acquista</a>', "https://ccb.18tickets.it/": STOREFRONT})
    up = check({"website": "https://cinemabo.it/"}, one)
    assert up["status"] == "active" and up["booking_url"] == "https://odeon.ccb.18tickets.it/"
