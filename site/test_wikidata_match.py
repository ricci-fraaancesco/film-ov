"""Tests for the Wikidata matcher (no network). Run: cd site && python -m pytest -q"""
from films import film_key, query_variants
from wikidata_match import candidate_from, choose, evidence, first_sentence, same_person


def cand(qid, names, year=None, directors=(), sitelinks=10):
    return {"qid": qid, "names": list(names), "year": year, "directors": list(directors), "sitelinks": sitelinks}


def test_film_key_and_variants():
    assert film_key("DUNE - PARTE TRE | 70MM") == film_key("Dune - Parte tre")
    assert film_key("THE ROCKY HORROR PICTURE SHOW (ED. SPEC.)") == "the rocky horror picture show"
    v = query_variants("PRANZO ALLE OTTO (DINNER AT EIGHT)")
    assert v[:3] == ["PRANZO ALLE OTTO (DINNER AT EIGHT)", "DINNER AT EIGHT", "PRANZO ALLE OTTO"]


def test_exact_title_unique_is_high():
    c = [cand("Q1", ["Taxi Driver"], 1976, ["Martin Scorsese"], 80)]
    best, conf, _ = choose(c, query_variants("TAXI DRIVER"), {})
    assert best["qid"] == "Q1" and conf == "high"


def test_remake_resolved_by_director():
    c = [cand("Q88", ["The Vanishing", "Spoorloos"], 1988, ["George Sluizer"], 30),
         cand("Q18", ["The Vanishing"], 2018, ["Kristoffer Nyholm"], 25)]
    best, conf, _ = choose(c, query_variants("THE VANISHING"), {"director": "Kristoffer Nyholm"})
    assert best["qid"] == "Q18" and conf == "high"


def test_remake_without_evidence_is_medium():
    c = [cand("Q88", ["The Vanishing"], 1988, ["George Sluizer"], 30),
         cand("Q18", ["The Vanishing"], 2018, ["Kristoffer Nyholm"], 25)]
    _, conf, _ = choose(c, query_variants("THE VANISHING"), {})
    assert conf == "medium"


def test_full_title_beats_half_title():
    c = [cand("Q_happy", ["Happiness - Felicità", "Happiness"], 1998, ["Todd Solondz"], 40),
         cand("Q_fel", ["Felicità"], 2023, ["Micaela Ramazzotti"], 60)]
    best, _, _ = choose(c, query_variants("HAPPINESS - FELICITA'"), {})
    assert best["qid"] == "Q_happy"


def test_wrong_director_rejected_or_demoted():
    c = [cand("Q1", ["Hope"], 2019, ["Maria Sødahl"], 20)]
    best, conf, _ = choose(c, query_variants("HOPE"), {"director": "Na Hong-jin"})
    assert conf != "high"


def test_no_match():
    best, conf, _ = choose([cand("Q1", ["Something Else"])], query_variants("DIGGER"), {})
    assert best is None and conf == "none"


def test_same_person():
    assert same_person("Alejandro G. Iñárritu", "Alejandro González Iñárritu")
    assert same_person("Federico Fellini", "federico fellini")
    assert not same_person("Paul Anderson", "Wes Anderson")


def test_evidence_year():
    d, _ = evidence({"year": 2026, "directors": []}, {"year": 2026})
    assert d > 0


def test_first_sentence():
    t = "Taxi Driver è un film del 1976 diretto da Martin Scorsese. Il film vinse la Palma d'oro."
    assert first_sentence(t) == "Taxi Driver è un film del 1976 diretto da Martin Scorsese."
    t2 = "M - Il mostro di Düsseldorf (M - Eine Stadt sucht einen Mörder) è un film del 1931 diretto da Fritz Lang. Altro."
    assert first_sentence(t2).endswith("Fritz Lang.")


def test_candidate_from_entity():
    e = {
        "labels": {"it": {"value": "Ombre"}, "en": {"value": "Shadows"}},
        "claims": {
            "P1476": [{"mainsnak": {"datavalue": {"value": {"text": "Shadows", "language": "en"}}}, "rank": "normal"}],
            "P577": [{"mainsnak": {"datavalue": {"value": {"time": "+1959-11-11T00:00:00Z"}}}, "rank": "normal"},
                     {"mainsnak": {"datavalue": {"value": {"time": "+1961-03-01T00:00:00Z"}}}, "rank": "normal"}],
            "P57": [{"mainsnak": {"datavalue": {"value": {"id": "Q51511"}}}, "rank": "normal"}],
            "P364": [{"mainsnak": {"datavalue": {"value": {"id": "Q1860"}}}, "rank": "normal"}],
            "P2047": [{"mainsnak": {"datavalue": {"value": {"amount": "+81", "unit": "http://www.wikidata.org/entity/Q7727"}}}, "rank": "normal"}],
            "P345": [{"mainsnak": {"datavalue": {"value": "tt0053270"}}, "rank": "normal"}],
        },
        "sitelinks": {"itwiki": {"title": "Ombre (film 1959)"}, "enwiki": {"title": "Shadows (1959 film)"}},
    }
    c = candidate_from("Q1", e)
    assert c["title_it"] == "Ombre" and c["original_title"] == "Shadows"
    assert c["year"] == 1959 and c["runtime"] == 81 and c["imdb"] == "tt0053270"
    assert c["director_ids"] == ["Q51511"] and c["language_ids"] == ["Q1860"]
    assert c["itwiki"] == "Ombre (film 1959)" and c["sitelinks"] == 2


def test_half_title_with_other_year_is_rejected():
    c = [cand("Q_dune1", ["Dune"], 2021, ["Denis Villeneuve"], 90)]
    best, conf, _ = choose(c, query_variants("DUNE - PARTE TRE"), {"director": "Denis Villeneuve", "year": 2026})
    assert best is None


def test_part3_found_when_present():
    c = [cand("Q_dune1", ["Dune"], 2021, ["Denis Villeneuve"], 90),
         cand("Q_dune3", ["Dune - Parte tre", "Dune: Part Three"], 2026, ["Denis Villeneuve"], 20)]
    best, conf, _ = choose(c, query_variants("DUNE - PARTE TRE"), {"director": "Denis Villeneuve", "year": 2026})
    assert best["qid"] == "Q_dune3" and conf == "high"
    best, conf, _ = choose(c, query_variants("DUNE: PART THREE"), {"director": "Denis Villeneuve", "year": 2026})
    assert best["qid"] == "Q_dune3"


def test_long_italian_title_matches_short_cinema_title():
    long = "Il dottor Stranamore - Ovvero: come ho imparato a non preoccuparmi e ad amare la bomba"
    c = [cand("Q_s", [long, "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb"], 1964, ["Stanley Kubrick"], 90)]
    best, conf, _ = choose(c, query_variants("IL DOTTOR STRANAMORE"), {"director": "Stanley Kubrick", "year": 1964})
    assert best["qid"] == "Q_s" and conf == "high"


def test_remakes_by_same_director_go_to_review():
    c = [cand("Q88", ["Il mistero della donna scomparsa", "The Vanishing", "Spoorloos"], 1988, ["George Sluizer"], 30),
         cand("Q93", ["The Vanishing - Scomparsa", "The Vanishing"], 1993, ["George Sluizer"], 35)]
    _, conf, _ = choose(c, query_variants("THE VANISHING"), {"director": "George Sluizer", "year": 2026})
    assert conf == "medium"


def test_both_halves_make_a_full_match():
    c = [cand("Q_p", ["Pranzo alle otto", "Dinner at Eight"], 1933, ["George Cukor"], 30)]
    best, conf, _ = choose(c, query_variants("PRANZO ALLE OTTO (DINNER AT EIGHT)"), {})
    assert best["qid"] == "Q_p" and conf == "high"


def test_director_spelling_variants():
    assert same_person("Martin Mc Donagh", "Martin McDonagh")
    assert same_person("Hirokazu Koreeda", "Hirokazu Kore-eda")


def test_same_title_no_director_other_year_rejected():
    c = [cand("Q2020", ["The Clearing"], 2020, [], 5)]
    best, _, _ = choose(c, query_variants("THE CLEARING"), {"director": "Sabine Groenewegen", "year": 2026})
    assert best is None


def test_no_director_on_wikidata_is_medium():
    c = [cand("Q1", ["Some Film"], 2024, [], 5)]
    _, conf, _ = choose(c, query_variants("SOME FILM"), {"director": "Jane Doe", "year": 2026})
    assert conf == "medium"


def test_non_latin_director_is_ignored():
    c = [cand("Q1", ["Sheep in the Box"], 2026, ["Hirokazu Kore-eda"], 5)]
    _, conf, _ = choose(c, query_variants("SHEEP IN THE BOX"), {"director": "是枝裕和", "year": 2026})
    assert conf == "high"
