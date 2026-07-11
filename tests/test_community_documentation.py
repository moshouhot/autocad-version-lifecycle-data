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

if __name__ == "__main__": unittest.main()
