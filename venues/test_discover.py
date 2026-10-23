"""Tests for the website / platform check (no network)."""
from collections import Counter

from discover import analyse, apply_updates, check, diff_rows, run, storefront_of

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
    up = check({"website": "https://www.thespacecinema.it/i-nostri-cinema/roma-moderno"}, FakeFetch({}))
    assert up["status"] == "adapter_missing" and up["platform"] == "thespace"
    assert check({"website": "cinemadown.it"}, FakeFetch({}))["status"] == "website_down"
    nothing = FakeFetch({"http://cinemavuoto.it": "<html><a href='/chi-siamo'>Chi siamo</a></html>"})
    assert check({"website": "cinemavuoto.it"}, nothing)["status"] == "no_booking_link"
    wt = FakeFetch({"https://cinemawt.it/": '<a href="https://www.webtic.it/#/shopping?action=loadLocal&localId=5013">Biglietti</a>'})
    up = check({"website": "https://cinemawt.it/"}, wt)
    # Webtic is now test-read; this fake has no network, so the read fails and goes to review
    assert up["status"] == "needs_review" and up["platform"] == "webtic" and "Webtic non letto" in up["note"]


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


def test_updates_survive_a_newer_list():
    before = [{"id": "a", "status": "to_check", "website": "https://a.it", "platform": "", "booking_url": "", "note": "", "last_checked": ""},
              {"id": "b", "status": "to_check", "website": "", "platform": "", "booking_url": "", "note": "", "last_checked": ""}]
    after = [dict(before[0], status="active", platform="18tickets", booking_url="https://a.x.18tickets.it/", last_checked="t"),
             dict(before[1], status="no_website", last_checked="t")]
    upd = diff_rows(before, after)
    assert upd["a"]["status"] == "active" and "website" not in upd["a"]
    # meanwhile the list was rebuilt (new cinema c) and a person fixed b by hand
    newer = [dict(before[0]), dict(before[1], status="manual_review", note="by hand"),
             {"id": "c", "status": "to_check", "website": "", "platform": "", "booking_url": "", "note": "", "last_checked": ""}]
    assert apply_updates(newer, upd) == 1
    assert newer[0]["status"] == "active" and newer[1]["status"] == "manual_review" and newer[2]["status"] == "to_check"


def test_main_storefront_and_shared_page():
    main_sf = STOREFRONT.replace("odeon.ccb.18tickets.it", "jollyroma.18tickets.it")
    f = FakeFetch({"https://jolly.it/": '<a href="https://jollyroma.18tickets.it/">Acquista</a>', "https://jollyroma.18tickets.it/": main_sf})
    up = check({"website": "https://jolly.it/"}, f)
    assert up["status"] == "active" and up["booking_url"] == "https://jollyroma.18tickets.it/"
    rows = [
        {"id": "v", "name": "Visionario", "city": "Udine", "sources": "cinemarevolution", "website": "", "status": "active", "platform": "18tickets", "booking_url": "https://odeon.ccb.18tickets.it/", "note": "", "last_checked": "", "region": ""},
        {"id": "c", "name": "Centrale", "city": "Udine", "sources": "cinemarevolution", "website": "https://centrale.it/", "status": "to_check", "platform": "", "booking_url": "", "note": "", "last_checked": "", "region": ""},
    ]
    f2 = FakeFetch({"https://centrale.it/": '<a href="https://odeon.ccb.18tickets.it/film/1/x">Acquista</a>', "https://odeon.ccb.18tickets.it/": STOREFRONT})
    run(rows, f2, batch=5, now="t")
    assert rows[1]["status"] == "needs_review" and "Visionario" in rows[1]["note"]


def test_webtic_cinema_is_test_read_and_activated(monkeypatch):
    import webtic
    calls = []

    def fake_read(get_json, lid, cinema="", city=""):
        calls.append(lid)
        from ov18tickets import Show
        s = Show("webtic.it", lid, "", "", "wt1-1", "X", "X", "Italiano", "", "2026-10-22T21:00:00+02:00", "2026-10-22", "21:00", "A", "u", False, "")
        return [s], {}, {"DistrictAbbreviation": "MI", "Description": "MULTISALA ORFEO", "Town": "Milano"}
    monkeypatch.setattr(webtic, "read_cinema", fake_read)
    f = FakeFetch({"https://orfeo.it/": '<a href="https://www.webtic.it/app/shopping/loadLocal/MI/5351">Acquista</a>'})
    f.s, f.delay = None, 0
    up = check({"website": "https://orfeo.it/"}, f)
    assert calls == ["5351"] and up["status"] == "active" and up["platform"] == "webtic"
    assert up["booking_url"] == "https://www.webtic.it/app/shopping/loadLocal/MI/5351" and "1 film" in up["note"]
    script_only = FakeFetch({"https://ci.it/": '<script src="https://secure.webtic.it/angwt/js/webapi/jquery.webtic.api.4.0.js"></script>'})
    up = check({"website": "https://ci.it/"}, script_only)
    assert up["status"] == "needs_review" and "non trovato" in up["note"]
    embed = FakeFetch({"https://ci2.it/": '<script src="https://secure.webtic.it/angwt/js/webapi/jquery.webtic.api.4.0.js"></script><script>webtic.init({localId=5221})</script>'})
    embed.s, embed.delay = None, 0
    assert check({"website": "https://ci2.it/"}, embed)["status"] == "active" and calls[-1] == "5221"


def test_uci_is_read_as_a_chain():
    up = check({"website": "https://www.ucicinemas.it/cinema/lazio/roma/uci-cinemas-roma-est/"}, FakeFetch({}))
    assert up["status"] == "active" and up["platform"] == "uci"


def test_white_label_webtic(monkeypatch):
    import webtic
    calls = []

    def fake_read(get_json, lid, cinema="", city=""):
        calls.append(lid)
        from ov18tickets import Show
        s = Show("webtic.it", lid, "", "", "wt1-1", "X", "X", "Italiano", "", "2026-10-22T21:00:00+02:00", "2026-10-22", "21:00", "A", "u", False, "")
        return [s], {}, {"DistrictAbbreviation": "RM", "Description": "TRIANON", "Town": "Roma"}
    monkeypatch.setattr(webtic, "read_cinema", fake_read)
    # booking links on the cinema's own domain, no "webtic" anywhere on the page
    f = FakeFetch({"https://www.mycityplex.it/trianon/": '<a href="/generic/seatsframe.php?sc=5279&amp;sp=84312#seatsframe">Acquista</a>'})
    f.s, f.delay = None, 0
    up = check({"website": "https://www.mycityplex.it/trianon/"}, f)
    assert calls == ["5279"] and up["status"] == "active" and up["booking_url"] == "https://www.webtic.it/app/shopping/loadLocal/RM/5279"
    # number already known from review: no page fetch, even for a chain site
    g = FakeFetch({})
    g.s, g.delay = None, 0
    up = check({"website": "https://www.notoriouscinemas.it/merlata/index.php", "platform": "webtic",
                "booking_url": "https://www.notoriouscinemas.it/generic/seatsframe.php?sc=5779&sp=52539#seatsframe"}, g)
    assert g.calls == [] and calls[-1] == "5779" and up["status"] == "active"
