import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import crawl_community_documentation as crawler

FIXTURES = Path(__file__).parent / "fixtures" / "community"

def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")

class CadForumParserTests(unittest.TestCase):
    def test_plus_name_is_percent_encoded(self):
        self.assertEqual(crawler.cadforum_url("+CUSTOMIZE", "command"), "https://www.cadforum.cz/en/command.asp?cmd=%2BCUSTOMIZE")

    def test_command_page_requires_exact_name(self):
        ev = crawler.parse_cadforum_html(fixture("cadforum_command.html"), "https://www.cadforum.cz/en/command.asp?cmd=*SCROLL", "*SCROLL", "command")
        self.assertEqual(ev.match_status, "matched")
        self.assertEqual(ev.matched_name, "*SCROLL")
        self.assertEqual(ev.first_version_text, "≤ R12")

    def test_variable_fields(self):
        ev = crawler.parse_cadforum_html(fixture("cadforum_variable.html"), "https://www.cadforum.cz/en/variable.asp?cmd=ACISOUTVER", "ACISOUTVER", "system_variable")
        self.assertEqual(ev.description, "Controls the ACIS version used for files exported by ACISOUT")
        self.assertEqual(ev.obsolete_text, "Variable no longer supported!")

    def test_not_found_template_is_not_a_match(self):
        ev = crawler.parse_cadforum_html(fixture("cadforum_not_found.html"), "https://www.cadforum.cz/en/command.asp?cmd=MISSING", "MISSING", "command")
        self.assertEqual(ev.match_status, "not_found")

class HyperPicsParserTests(unittest.TestCase):
    def test_index_keeps_exact_variable_names_and_version_summary(self):
        index = crawler.parse_hyperpics_index(fixture("hyperpics_variables.html"), "http://www.hyperpics.com/system_variables/")
        self.assertIn("ACISOUTVER", index)
        self.assertIn("ACISOUT", index)
        self.assertEqual(index["ACISOUTVER"].match_status, "matched")
        self.assertEqual(index["ACISOUTVER"].first_version_text, "2004 or earlier")
        self.assertEqual(index["ACISOUTVER"].product_notes["available_versions"], ["2004", "2005"])


class VersionComparisonTests(unittest.TestCase):
    def test_early_release_claim_and_upper_bound(self):
        self.assertLess(crawler.parse_first_version("R14").sort_key, crawler.parse_first_version("2004").sort_key)
        self.assertEqual(crawler.parse_first_version("≤ R12").kind, "upper_bound")
        self.assertEqual(crawler.parse_first_version("very old").kind, "unknown")

    def test_obsolete_alone_does_not_mean_removed(self):
        record = {"type":"system_variable","availability":[{"from":"2004","to":"2027"}],"available_in_latest":True,"removed_in":[]}
        metadata = {"version_axes":{"system_variable":["2004","2012","2027"]}}
        ev = crawler.SourceEvidence("cadforum","https://www.cadforum.cz/x","matched","BLIPMODE",obsolete_text="Obsolete since 2012")
        comparisons, conflicts = crawler.compare_source_to_lifecycle(record, ev, metadata)
        self.assertFalse(conflicts)
        self.assertTrue(any(x.claim == "obsolete_status" and x.result == "unknown" for x in comparisons))

    def test_explicit_no_longer_supported_can_conflict(self):
        record = {"type":"system_variable","availability":[{"from":"2004","to":"2027"}],"available_in_latest":True,"removed_in":[]}
        metadata = {"version_axes":{"system_variable":["2004","2012","2027"]}}
        ev = crawler.SourceEvidence("cadforum","https://www.cadforum.cz/x","matched","X",obsolete_text="Variable no longer supported since 2012")
        _, conflicts = crawler.compare_source_to_lifecycle(record, ev, metadata)
        self.assertEqual(conflicts[0].field, "availability")

class EvidenceClassifierTests(unittest.TestCase):
    def test_all_five_statuses_and_conflict_priority(self):
        matched1 = crawler.SourceEvidence("cadforum","u","matched","X",first_version_text="R14")
        matched2 = crawler.SourceEvidence("hyperpics","v","matched","X",first_version_text="2004 or earlier")
        consistent = crawler.Comparison("first_known_version","consistent","ok")
        conflict = crawler.Conflict("availability","lifecycle available","source removed","runtime verification")
        self.assertEqual(crawler.classify_evidence([matched1, matched2],[consistent],[]), "confirmed")
        self.assertEqual(crawler.classify_evidence([matched1],[consistent],[]), "corroborated")
        self.assertEqual(crawler.classify_evidence([crawler.SourceEvidence("cadforum","u","matched","X")],[],[]), "single_source")
        self.assertEqual(crawler.classify_evidence([],[],[]), "not_found")
        self.assertEqual(crawler.classify_evidence([matched1,matched2],[consistent],[conflict]), "conflict")

class RelatedItemTests(unittest.TestCase):
    def test_extracts_explicit_acisout_relation_without_substrings(self):
        records=[{"id":"cmd-1","name":"ACISOUT","type":"command"},{"id":"sysvar-1","name":"ACISOUTVER","type":"system_variable"},{"id":"cmd-2","name":"CUSTOM","type":"command"}]
        catalog=crawler.build_name_catalog(records)
        items=crawler.extract_related_items("Controls the ACIS version used for files exported by ACISOUT.", records[1], catalog, "https://www.cadforum.cz/x")
        self.assertEqual([(x.name,x.type,x.relation) for x in items], [("ACISOUT","command","controlled_command")])
        self.assertEqual(crawler.extract_related_items("The value is customizable.", records[1], catalog, "u"), [])
if __name__ == "__main__": unittest.main()
