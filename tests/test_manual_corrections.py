import csv
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apply_manual_corrections import apply_corrections, load_overrides


def make_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w=csv.DictWriter(f,fieldnames=headers)
        w.writeheader();w.writerows(rows)


class ManualOverridesTests(unittest.TestCase):
    def test_only_verified_overrides_applied_and_original_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            headers=['redial_movie_id','wikidata_qid','match_status','match_reason','wikidata_url','suggested_wikidata_qid']
            data=[{'redial_movie_id':'1','wikidata_qid':'','match_status':'needs_review','match_reason':'ambiguous', 'wikidata_url':'','suggested_wikidata_qid':'Q3'},
                  {'redial_movie_id':'2','wikidata_qid':'Q5','match_status':'auto_matched','match_reason':'high score','wikidata_url':'link','suggested_wikidata_qid':'Q5'},
                  {'redial_movie_id':'3','wikidata_qid':'','match_status':'needs_review','match_reason':'no year','wikidata_url':'','suggested_wikidata_qid':'Q9'}]
            matches=d/'matches.csv';make_csv(matches,headers,data)
            override=d/'overrides.csv';make_csv(override,['redial_movie_id','wikidata_qid','review_status','review_notes'],
                [{'redial_movie_id':'1','wikidata_qid':'Q100','review_status':'verified','review_notes':'checked'},
                 {'redial_movie_id':'3','wikidata_qid':'Q200','review_status':'pending','review_notes':'not yet'}])
            result=apply_corrections(matches,override,d/'out')
            self.assertEqual(result,{'rows_processed':3,'manual_verified':1,'auto_matched':1,'remaining_for_review':1})
            self.assertEqual(list(csv.DictReader(matches.open()))[0]['wikidata_qid'],'')
            output=list(csv.DictReader((d/'out/final_matches.csv').open(encoding='utf-8-sig')))
            self.assertEqual(output[0]['wikidata_qid'],'Q100')
            self.assertEqual(output[0]['mapping_source'],'human_review')
            self.assertEqual(output[0]['suggested_wikidata_qid'],'Q3')
            self.assertEqual(output[1]['mapping_source'],'auto_match')
            self.assertEqual(output[2]['mapping_source'],'unresolved')
            self.assertEqual(len(list(csv.DictReader((d/'out/final_review_queue.csv').open(encoding='utf-8-sig')))),1)

    def test_reject_invalid_verified_qid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.csv'
            make_csv(path,['redial_movie_id','wikidata_qid','review_status','review_notes'],
                     [{'redial_movie_id':'187028','wikidata_qid':'not a QID','review_status':'verified','review_notes':''}])
            with self.assertRaises(ValueError):load_overrides(path)

    def test_reject_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.csv'
            make_csv(path,['redial_movie_id','wikidata_qid','review_status','review_notes'],
                     [{'redial_movie_id':'187028','wikidata_qid':'Q1','review_status':'verified','review_notes':''},
                      {'redial_movie_id':'187028','wikidata_qid':'Q2','review_status':'verified','review_notes':''}])
            with self.assertRaises(ValueError):load_overrides(path)

if __name__=='__main__':unittest.main()
