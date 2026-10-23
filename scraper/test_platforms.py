"""Tests for the Webtic and UCI adapters, on data shaped like the real responses (no network)."""
from pathlib import Path

import uci
import webtic
from ov18tickets import run_platforms

WT_INFO = {"DS": {"Local": {"LocalId": 5351, "Description": "MULTISALA ORFEO", "DistrictAbbreviation": "MI", "Town": "Milano"}}}
WT_SCHED = {"DS": {"Scheduling": {"LocalId": 5351, "Events": [
    {"EventId": 3006, "Title": "Ragione E Sentimento (2026)", "OriginalTitle": "Sense and Sensibility",
     "Description": "<p>Le sorelle Dashwood...</p>", "Director": "Georgia Oakley", "Year": "2026", "Category": "Dramma",
     "Picture": "HandlerLocandinaEx.ashx?idcinema=5351&idevento=3006&i=jpg-m",
     "Properties": ["2D"], "EventProperties": [
         {"EventProperty": "2D", "EventPropertyCategory": "SCREEN"},
         {"EventProperty": "O.V.", "EventPropertyCategory": "CATEGORIA NON DEFINITA"},
         {"EventProperty": "EN", "EventPropertyCategory": "LANGUAGE"},
         {"EventProperty": "SUB-IT", "EventPropertyCategory": "SUBTITLES"}],
     "Days": [{"Day": "2026-10-22T00:00:00", "Performances": [
         {"PerformanceId": 177100, "Time": "21:15", "Screen": "BLU", "ScreenName": "SALA BLU", "StartTime": "2026-10-22T21:15:00"}]}]},
    {"EventId": 2996, "Title": "Avengers: Doomsday In 4k (It)", "Properties": ["2D"],
     "EventProperties": [{"EventProperty": "2D", "EventPropertyCategory": "SCREEN"}],
     "Days": [{"Day": "2026-12-16T00:00:00", "Performances": [
         {"PerformanceId": 176930, "Screen": "ROSSA", "StartTime": "2026-12-16T15:10:00"}]}]},
    {"EventId": 3010, "Title": "Seventeen World Tour", "EventProperties": [{"EventProperty": "KOR", "EventPropertyCategory": "CATEGORIA NON DEFINITA"},
                                                                  {"EventProperty": "SUB-EN", "EventPropertyCategory": "CATEGORIA NON DEFINITA"}],
     "Days": [{"Performances": [{"PerformanceId": 1, "Screen": "A", "StartTime": "2026-10-25T20:00:00"}]}]},
]}}}

UCI_THEATRES = {"data": [{"id": 5, "name": "UCI Cinemas Porta di Roma", "slug": "uci-cinemas-porta-di-roma-roma",
                          "city": "Roma", "address": "<p>Via delle Vigne Nuove, snc<br>Roma</p>", "latitude": "41.97", "longitude": "12.54"}]}
UCI_PROG = {"data": [
    {"2026-10-26": [{"id": 7400, "title": "Ragione e sentimento", "slug": "ragione-e-sentimento", "poster": "https://storage.googleapis.com/p.jpg",
                     "description": "<p>Le sorelle Dashwood...</p><p><strong>Si ricorda che il film inizia circa 25 minuti dopo</strong></p>",
                     "genres": [{"name": "Drammatico"}],
                     "screens": [{"2D": [
                         {"slug": "ov-sense-and-sensibility-2026", "language": {"name": "ENG", "slug": "EN"}, "subtitles": {"name": "ITA"},
                          "release_date": 2026, "performances": [{"id": 1375680, "room": "SALA7", "starts_at": "2026-10-26 16:50:00",
                                                                  "cart_link": "/movies/ragione-e-sentimento/acquista/5119/8689/1276241"}]},
                         {"slug": "ragione-e-sentimento", "language": {"name": "ITA"}, "subtitles": None,
                          "performances": [{"id": 1375681, "room": "SALA2", "starts_at": "2026-10-26 18:00:00", "cart_link": "/movies/x/acquista/1/2/3"}]}]}]}]},
    {"2026-10-27": [{"id": 7400, "title": "Ragione e sentimento", "slug": "ragione-e-sentimento", "screens": [{"2D": [
        {"language": {"name": "ENG"}, "subtitles": {"name": "ITA"},
         "performances": [{"id": 1375680, "room": "SALA7", "starts_at": "2026-10-26 16:50:00", "cart_link": "/movies/ragione-e-sentimento/acquista/5119/8689/1276241"}]}]}]}]},
]}


def test_local_id_from_any_link():
    assert webtic.local_id_from_url("https://www.webtic.it/#/shopping?action=loadLocal&localId=5106") == "5106"
    assert webtic.local_id_from_url("https://www.webtic.it/app/shopping/loadLocal/RM/5513") == "5513"
    assert webtic.local_id_from_url("https://www.webtic.it/app/shopping/loadEvent/VA/5264/14206/3968") == "5264"
    assert webtic.local_id_from_url("https://secure.webtic.it/api/HandlerLocandinaEx.ashx?idcinema=5416&idevento=2936") == "5416"
    assert webtic.local_id_from_url("https://www.webtic.it/#/shopping?action=loadLocal\\u0026localId=5332") == "5332"
    import base64
    pu = base64.b64encode(b"https://www.webtic.it/index.htm#/home?action=loadLocal&localId=5652").decode()
    assert webtic.local_id_from_url(f"https://secure.webtic.it/angwt/webtic.aspx?pu={pu}") == "5652"
    assert webtic.local_id_from_url("https://secure.webtic.it/angwt/js/webapi/jquery.webtic.api.4.0.js") is None
    # white-label Webtic sites
    assert webtic.local_id_from_url("https://www.mycityplex.it/generic/seatsframe.php?sc=5283&sp=61404#seatsframe") == "5283"
    assert webtic.local_id_from_url("https://www.notoriouscinemas.it/generic/seatsframe.php?sc=5779&amp;sp=52539") == "5779"
    assert webtic.local_id_from_url("https://www.staseraalcinema.it/film-ricercato/?mult=5048&per=61158&pro=4325") == "5048"
    assert webtic.local_id_from_url("https://www.example.it/page.php?sc=5283") is None


def test_webtic_parse():
    calls = []

    def get_json(url, params):
        calls.append(params["wtid"])
        return WT_INFO if params["wtid"] == "getLocalInfo" else WT_SCHED

    shows, pages, info = webtic.read_cinema(get_json, "5351", "Multisala Orfeo", "Milano")
    assert calls == ["getLocalInfo", "getFullScheduling"]
    ov = [s for s in shows if s.is_ov]
    assert len(shows) == 3 and len(ov) == 2
    s = next(x for x in ov if x.film_id == "wt5351-3006")
    assert s.language == "Inglese con sottotitoli in italiano" and s.subtitles == "sub IT"
    assert s.starts_at == "2026-10-22T21:15:00+02:00" and s.screen == "Sala Blu"
    assert s.booking_url == "https://www.webtic.it/app/shopping/loadEvent/MI/5351/177100/3006"
    assert pages[s.film_url]["director"] == "Georgia Oakley" and pages[s.film_url]["year"] == 2026
    assert pages[s.film_url]["poster"].startswith("https://secure.webtic.it/angwt/HandlerLocandinaEx.ashx")
    k = next(x for x in ov if x.film_id == "wt5351-3010")
    assert k.language == "Coreano con sottotitoli in inglese"
    assert not next(x for x in shows if x.film_id == "wt5351-2996").is_ov


def test_uci_parse():
    t = uci.theatres(lambda u, p: UCI_THEATRES)
    assert t[0]["address"] == "Via delle Vigne Nuove, snc" and t[0]["city"] == "Roma"
    shows, pages = uci.parse_programming(UCI_PROG, t[0])
    assert len(shows) == 2  # the repeated performance on the next day block is counted once
    ov = [s for s in shows if s.is_ov]
    assert len(ov) == 1
    s = ov[0]
    assert s.language == "Inglese con sottotitoli in italiano" and s.time == "16:50" and s.screen == "Sala7"
    assert s.booking_url == "https://ucicinemas.it/movies/ragione-e-sentimento/acquista/5119/8689/1276241"
    pg = pages["https://ucicinemas.it/movies/ragione-e-sentimento"]
    assert pg["synopsis"] == "Le sorelle Dashwood..." and pg["poster"].endswith("p.jpg")
    uci.add_directors(lambda u, p: {"data": {"directors": [{"name": "Georgia Oakley"}]}}, pages, {})
    assert pg["director"] == "Georgia Oakley"


def test_run_platforms(tmp_path):
    venues = tmp_path / "venues.csv"
    venues.write_text("name,city,status,platform,booking_url\n"
                      "Multisala Orfeo,Milano,active,webtic,https://www.webtic.it/app/shopping/loadLocal/MI/5351\n"
                      "Cinema X,Roma,adapter_missing,webtic,https://www.webtic.it/app/shopping/loadLocal/RM/9999\n", encoding="utf-8")

    def get_json(url, params=None):
        if "wtjsonservices" in url:
            assert params["localid"] == "5351"  # only the active cinema is read
            return WT_INFO if params["wtid"] == "getLocalInfo" else WT_SCHED
        if url.endswith("/theatres"):
            return UCI_THEATRES
        if url.endswith("/programming"):
            return UCI_PROG
        return {"data": {"directors": [{"name": "Georgia Oakley"}]}}

    pages = tmp_path / "film_pages.json"
    shows, errors = run_platforms(venues, pages, get_json=get_json, uci=True)
    assert not errors and len(shows) == 5
    import json
    cache = json.loads(pages.read_text())
    assert cache["https://ucicinemas.it/movies/ragione-e-sentimento"]["director"] == "Georgia Oakley"
    assert all("checked" in v for v in cache.values())


def test_uci_stops_on_refusal(tmp_path):
    import requests
    calls = []

    def get_json(url, params=None):
        calls.append(url)
        if url.endswith("/theatres"):
            return {"data": [{"slug": "a", "name": "A", "city": "X"}, {"slug": "b", "name": "B", "city": "Y"}]}
        resp = requests.Response(); resp.status_code = 403
        raise requests.HTTPError("403", response=resp)
    shows, errors = run_platforms(None, tmp_path / "pages.json", get_json=get_json, uci=True)
    assert shows == [] and "uci:stopped" in errors
    assert not any(u.endswith("/b/programming") for u in calls)


def test_uci_name_without_city_suffix():
    assert uci.clean_name("UCI Cinemas Parco Leonardo | Roma") == "UCI Cinemas Parco Leonardo"
    assert uci.clean_name("UCI Luxe Megalò |  Chieti ") == "UCI Luxe Megalò"
    assert uci.clean_name("UCI Cinemas Arezzo") == "UCI Cinemas Arezzo"
    assert uci.clean_name("| Roma") == "| Roma"
    t = uci.theatres(lambda u, p: {"data": [{"slug": "x", "name": "UCI Cinemas Bicocca | Milano", "city": "Milano"}]})
    assert t[0]["name"] == "UCI Cinemas Bicocca"


def test_uci_real_town_from_venues():
    th = uci.theatres(lambda u, p: {"data": [
        {"slug": "uci-cinemas-molfetta-bari", "name": "UCI Cinemas Molfetta | Bari", "city": "Bari", "province": "Bari"},
        {"slug": "uci-cinemas-fiumara-genova", "name": "UCI Luxe Fiumara | Genova", "city": "Genova"},
        {"slug": "uci-cinemas-torino-lingotto", "name": "UCI Cinemas Torino Lingotto", "city": "Torino"},
        {"slug": "uci-cinemas-megalo", "name": "UCI Luxe Megalò | Chieti", "city": "Chieti"},
        {"slug": "uci-new", "name": "UCI Cinemas Nuovo", "city": "X"}]})
    rows = [{"name": "Uci Cinemas Molfetta", "city": "Molfetta", "platform": "uci"},
            {"name": "Uci Cinemas Genova", "city": "Genova", "platform": "uci"},
            {"name": "Uci Cinemas Torino", "city": "Torino", "platform": "uci"},
            {"name": "Uci Cinemas Megalo'", "city": "Chieti", "platform": "uci"},
            {"name": "Cinema Molfetta", "city": "Molfetta", "platform": "18tickets"}]
    m = uci.match_venues(th, rows)
    assert m["uci-cinemas-molfetta-bari"]["city"] == "Molfetta"
    assert m["uci-cinemas-fiumara-genova"]["name"] == "Uci Cinemas Genova"
    assert m["uci-cinemas-torino-lingotto"]["city"] == "Torino"
    assert m["uci-cinemas-megalo"]["city"] == "Chieti"
    assert "uci-new" not in m
