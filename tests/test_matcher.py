import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikidata_matcher import (
    split_title_year, normalise_title, score_candidate, decide_match, load_movies, evaluate,
    get_ranked, enwiki_title_variants
)


def make_claim_year(year):
    return {"mainsnak": {"datavalue": {"value": {"time": f"+{year}-01-01T00:00:00Z"}}}}


def make_claim_id(qid):
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}


def entity(title, year=2017, qid_instance="Q11424", description="2017 American film", aliases=()):
    return {
        "labels": {"en": {"value": title}},
        "descriptions": {"en": {"value": description}},
        "aliases": {"en": [{"value": a} for a in aliases]},
        "claims": {"P577": [make_claim_year(year)], "P31": [make_claim_id(qid_instance)]},
    }


class MatcherTests(unittest.TestCase):
    def test_parse_year_with_double_spaces(self):
        self.assertEqual(split_title_year("It  (2017)"), ("It", 2017))
        self.assertEqual(split_title_year("Star Wars: Episode VIII (2017)"), ("Star Wars: Episode VIII", 2017))

    def test_yearless_is_not_fabricated(self):
        self.assertEqual(split_title_year("Back to Hannibal"), ("Back to Hannibal", None))

    def test_unicode_normalisation(self):
        self.assertEqual(normalise_title("Se7en"), "se7en")
        self.assertEqual(normalise_title("Café – Film"), "cafe film")

    def test_correct_wonder_woman_beats_different_film(self):
        movie = {"cleaned_title": "Wonder Woman", "release_year": 2017}
        correct = score_candidate(movie, "Q20502242", entity("Wonder Woman", 2017))
        wrong = score_candidate(movie, "Q27204179", entity("Professor Marston & The Wonder Women", 2017))
        ranked = sorted([correct, wrong], key=lambda x: x["score"], reverse=True)
        self.assertEqual(ranked[0]["qid"], "Q20502242")
        self.assertEqual(decide_match(movie, ranked)[0], "auto_matched")

    def test_short_title_is_not_auto_accepted(self):
        movie = {"cleaned_title": "It", "release_year": 2017}
        ranked = [score_candidate(movie, "Q25136484", entity("It", 2017))]
        self.assertEqual(decide_match(movie, ranked)[0], "needs_review")

    def test_missing_year_is_reviewed(self):
        movie = {"cleaned_title": "Deadpool", "release_year": None}
        ranked = [score_candidate(movie, "Q19347291", entity("Deadpool", 2016))]
        self.assertEqual(decide_match(movie, ranked)[0], "needs_review")

    def test_wrong_year_is_reviewed(self):
        movie = {"cleaned_title": "Coco", "release_year": 2017}
        ranked = [score_candidate(movie, "QX", entity("Coco", 1990))]
        self.assertNotEqual(decide_match(movie, ranked)[0], "auto_matched")

    def test_enwiki_title_variants(self):
        self.assertEqual(enwiki_title_variants("Seven", 1995), ["Seven (1995 film)", "Seven (film)"])
        self.assertEqual(enwiki_title_variants("Seven", None), [])

    def test_ambiguous_it_gets_film_candidate_from_enwiki_sitelink(self):
        class FakeClient:
            def search(self, query):
                return ["Q11661"]
            def details(self, qids):
                return {"Q11661": entity("information technology", 1999, description="field of technology")}
            def enwiki_lookup(self, title):
                return {"Q25136484": entity("It", 2017)} if title == "It (2017 film)" else {}

        movie = {"cleaned_title": "It", "release_year": 2017}
        ranked = get_ranked(movie, FakeClient())
        self.assertEqual(ranked[0]["qid"], "Q25136484")
        self.assertEqual(decide_match(movie, ranked)[0], "needs_review")  # short title remains manual

    def test_seven_wins_over_television_network_from_year_specific_sitelink(self):
        class FakeClient:
            def search(self, query):
                return ["Q908659"]
            def details(self, qids):
                return {"Q908659": entity("Seven Network", 1956, description="television network")}
            def enwiki_lookup(self, title):
                return {"Q190908": entity("Seven", 1995)} if title == "Seven (1995 film)" else {}

        movie = {"cleaned_title": "Seven", "release_year": 1995}
        ranked = get_ranked(movie, FakeClient())
        self.assertEqual(ranked[0]["qid"], "Q190908")
        self.assertEqual(decide_match(movie, ranked)[0], "auto_matched")

    def test_enwiki_candidate_with_wrong_year_is_not_auto_matched(self):
        class FakeClient:
            def search(self, query):
                return []
            def details(self, qids):
                return {}
            def enwiki_lookup(self, title):
                return {"Q999": entity("Seven", 2005)}
        movie = {"cleaned_title": "Seven", "release_year": 1995}
        ranked = get_ranked(movie, FakeClient())
        self.assertNotEqual(decide_match(movie, ranked)[0], "auto_matched")

    def test_input_file(self):
        movies = load_movies(Path(__file__).resolve().parents[1] / "data" / "movies_with_mentions.csv")
        self.assertEqual(len(movies), 6924)
        self.assertEqual((movies[0]["redial_movie_id"], movies[0]["mentions"]), ("204974", 1024))
        self.assertEqual(movies[0]["cleaned_title"], "Black Panther")


if __name__ == "__main__":
    unittest.main()
