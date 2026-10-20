"""Tests for the cinema list builder (no network)."""
from build_list import VenueList, build, parse_cr_page, parse_mm, parse_osm, same_name, smart_title

CR_HTML = """<table><tr><th>NOME</th><th>INDIRIZZO</th><th>CITTÀ</th><th>CAP</th><th>PROVINCIA</th></tr>
<tr><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td>CINEMA LUMIERE</td><td>VIA AZZO GARDINO 65</td><td>BOLOGNA</td><td>40122</td><td>BO</td></tr>
<tr><td>Cinema Multisala Eliseo di Poggiomarino</td><td>Traversa di Via Ferrovia n. 14</td><td>Poggiomarino</td><td>80040</td><td>NA</td></tr>
<tr><td>ARENA ESTIVA CASTELLO DELL'IMPERATORE</td><td>PIAZZA S.M. DELLE CARCERI</td><td>PRATO</td><td>59100</td><td>PO</td></tr>
</table>"""

MM_HTML = """<table><tr><th>Cinema</th><th>Città</th><th>Prov</th><th>Regione</th><th>Schermi</th></tr>
<tr><td>★ BARBERINI</td><td>ROMA</td><td>RM</td><td>Lazio</td><td>7</td></tr>
<tr><td>CINEMA TEATRO EDEN</td><td>NONE</td><td>TO</td><td>Piemonte</td><td>1</td></tr></table>"""

OSM = {"elements": [
    {"type": "node", "id": 1, "lat": 44.5, "lon": 11.33, "tags": {"amenity": "cinema", "name": "Cinema Lumière", "addr:city": "Bologna", "website": "https://cinetecadibologna.it"}},
    {"type": "way", "id": 2, "center": {"lat": 41.9, "lon": 12.48}, "tags": {"amenity": "cinema", "name": "Multisala Barberini", "addr:city": "Roma", "addr:street": "Piazza Barberini", "addr:housenumber": "24"}},
    {"type": "node", "id": 3, "lat": 45.0, "lon": 7.6, "tags": {"amenity": "cinema", "name": "Cinema Nuovo Distinto"}},
    {"type": "node", "id": 4, "lat": 45.0, "lon": 7.6, "tags": {"amenity": "cinema"}},
]}


def test_parsers():
    cr = parse_cr_page(CR_HTML)
    assert len(cr) == 3 and cr[0] == {"name": "Cinema Lumiere", "address": "Via Azzo Gardino 65", "city": "Bologna", "postcode": "40122", "province": "BO"}
    assert cr[1]["name"] == "Cinema Multisala Eliseo di Poggiomarino"  # mixed case kept
    mm = parse_mm(MM_HTML)
    assert mm[0]["name"] == "Barberini" and mm[0]["screens"] == "7" and "★" in mm[0]["note"]
    assert mm[1]["city"] == ""
    osm = parse_osm(OSM)
    assert len(osm) == 3 and osm[1]["lat"] == "41.900000" and osm[1]["address"] == "Piazza Barberini 24"


def test_names():
    assert smart_title("ROMA D'ESSAI") == "Roma d'Essai"
    assert smart_title("L'AQUILA") == "L'Aquila"
    assert same_name("Cinema Lumière", "CINEMA LUMIERE")
    assert same_name("Pop Up Cinema Jolly", "Jolly")
    assert same_name("Rialto Studios", "Rialto Studio")
    assert not same_name("Odeon", "Eden")


def test_merge():
    ours = [{"name": "Cinema Lumière", "city": "Bologna", "platform": "18tickets", "booking_url": "https://lumiere.x/", "status": "active"},
            {"name": "Multisala Barberini", "city": "Roma", "platform": "18tickets", "status": "active"}]
    rows, stats = build(parse_cr_page(CR_HTML), parse_mm(MM_HTML), parse_osm(OSM), ours, {})
    by = {r["name"]: r for r in rows}
    lum = by["Cinema Lumière"]
    assert lum["address"] == "Via Azzo Gardino 65" and lum["website"] == "https://cinetecadibologna.it"
    assert lum["sources"] == "filmov|cinemarevolution|osm" and lum["status"] == "active" and lum["region"] == "Emilia-Romagna"
    bar = by["Multisala Barberini"]
    assert bar["screens"] == "7" and bar["lat"] == "41.900000" and "moviemedia" in bar["sources"]
    assert by["Arena Estiva Castello dell'Imperatore"]["kind"] == "arena"
    assert by["Cinema Nuovo Distinto"]["status"] == "to_check" and by["Cinema Nuovo Distinto"]["city"] == ""
    assert stats["osm"] == {"rows": 3, "new": 1, "merged": 2}


def test_manual_work_is_kept():
    first, _ = build(parse_cr_page(CR_HTML), [], [], [], {})
    prev = {r["id"]: dict(r) for r in first}
    pid = next(i for i, r in prev.items() if "Eliseo" in r["name"])
    prev[pid].update({"status": "no_website", "note": "checked by hand"})
    again, _ = build(parse_cr_page(CR_HTML), [], [], [], prev)
    r = next(x for x in again if x["id"] == pid)
    assert r["status"] == "no_website" and r["note"] == "checked by hand"


def test_our_cinemas_load():
    from build_list import our_cinemas
    ours = our_cinemas()
    names = {o["name"] for o in ours}
    assert "Multisala Barberini" in names and "Cinema Lumière" in names
    assert all(o["platform"] == "18tickets" and o["booking_url"].startswith("https://") for o in ours)


def test_same_address_and_brand_names():
    vl = VenueList()
    vl.add({"name": "TSC Bologna (BO)", "city": "Bologna", "province": "BO", "address": "Viale Europa, 5"}, "cinemarevolution")
    assert vl.add({"name": "The Space Cinema", "city": "Bologna", "address": "Viale Europa 5"}, "osm") == "merged"
    vl.add({"name": "Sala 1", "city": "Roma", "address": "Via Giuseppe Verdi, 24"}, "cinemarevolution")
    assert vl.add({"name": "Sala 2", "city": "Roma", "address": "Via Giuseppe Verdi, 24"}, "cinemarevolution") == "merged"
    vl.add({"name": "Cinema Eden Roma", "city": "Roma", "address": "Piazza Cola di Rienzo 74"}, "cinemarevolution")
    assert vl.add({"name": "Eden Film Center", "city": "ROMA", "province": "RM"}, "moviemedia") == "merged"
    assert vl.add({"name": "Odeon", "city": "Roma"}, "osm") == "new"


def test_fill_towns_once(tmp_path):
    from build_list import fill_towns
    calls = []
    def fetch(lat, lon):
        calls.append((lat, lon))
        return {"town": "Ciampino", "postcode": "00043", "ISO3166-2-lvl6": "IT-RM", "road": "Via Roma", "house_number": "3"}
    osm = [{"name": "Il Piccolissimo", "city": "", "lat": "41.79", "lon": "12.60", "osm_id": "node/9", "address": ""}]
    assert fill_towns(osm, tmp_path / "t.json", fetch=fetch, delay=0) == 1
    assert osm[0]["city"] == "Ciampino" and osm[0]["province"] == "RM" and osm[0]["address"] == "Via Roma 3"
    osm2 = [{"name": "Il Piccolissimo", "city": "", "lat": "41.79", "lon": "12.60", "osm_id": "node/9", "address": ""}]
    assert fill_towns(osm2, tmp_path / "t.json", fetch=fetch, delay=0) == 0 and len(calls) == 1
