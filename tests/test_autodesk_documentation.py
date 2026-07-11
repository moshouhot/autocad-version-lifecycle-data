import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import crawl_autodesk_documentation as crawler

FIXTURES = Path(__file__).parent / "fixtures"

def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")

class DocumentParserTests(unittest.TestCase):
    def test_parse_2014_command_topic(self):
        topic = crawler.parse_topic_html(fixture("autodesk_2014_3dsin.html"), "http://docs.autodesk.com/x/GUID-A28A2118-11C4-49D3-B8E5-A99EE46C1D32.htm", "2014")
        self.assertEqual(topic.topic_type, "command")
        self.assertEqual(topic.official_name, "3DSIN")
        self.assertEqual(topic.description, "Imports a 3ds Max (3DS) file.")
        self.assertEqual(len(topic.summary), 2)

    def test_parse_new_system_variable_and_dedupe_description(self):
        topic = crawler.parse_topic_html(fixture("autodesk_2027_sysvar.html"), "https://help.autodesk.com/cloudhelp/2027/x/GUID-7B01C113-0000-0000-0000-000000000000.htm", "2027")
        self.assertEqual(topic.topic_type, "system_variable")
        self.assertEqual(topic.official_name, "ACTIVITYINSIGHTSSTATE")
        self.assertEqual(topic.summary, ["Saved in: Registry & drawing."])

    def test_contextid_is_official_name_fallback(self):
        html = """<html><head><meta name="topic-subtype" content="command"><meta name="contextid" content="+CONSTRAINTSETTINGS"><meta name="description" content="Displays settings."><meta name="topicid" content="GUID-11111111-1111-1111-1111-111111111111"><title>+CONSTRAINTSETTINGS (Command)</title></head></html>"""
        topic = crawler.parse_topic_html(html, "https://help.autodesk.com/x/GUID-11111111-1111-1111-1111-111111111111.htm", "2027")
        self.assertEqual(topic.official_name, "+CONSTRAINTSETTINGS")

    def test_title_suffix_infers_missing_subtype(self):
        html = """<html><head><meta name="contextid" content="STYLUSFORCETHRESHOLD"><meta name="topicid" content="GUID-53A75210-CFDD-4B65-A96C-915957A0073C"><title>STYLUSFORCETHRESHOLD (System Variable)</title></head></html>"""
        topic = crawler.parse_topic_html(html, "https://help.autodesk.com/x/GUID-53A75210-CFDD-4B65-A96C-915957A0073C.htm", "2027")
        self.assertEqual(topic.topic_type, "system_variable")

    def test_search_response_filters_non_cloudhelp(self):
        entries = crawler.parse_search_response(json.loads(fixture("beehive_search.json")), "command")
        self.assertEqual([e.title for e in entries], ["3DSIN (Command)"])

class NameMatchingTests(unittest.TestCase):
    def test_name_candidates(self):
        self.assertEqual(crawler.name_candidates("'-ACTSTOP"), [("-ACTSTOP", "transparent_prefix")])
        self.assertEqual(crawler.name_candidates("-3DCONFIG"), [("-3DCONFIG", "exact")])
        self.assertEqual(crawler.name_candidates("AUTOCOMPLETE (INPUTSEARCHOPTIONS)"), [("AUTOCOMPLETE (INPUTSEARCHOPTIONS)", "exact"), ("AUTOCOMPLETE", "alias_primary"), ("INPUTSEARCHOPTIONS", "alias_parenthetical")])

    def test_match_exact_and_ambiguous(self):
        t1 = crawler.Topic("LINE", "LINE (Command)", "https://help.autodesk.com/a/GUID-11111111-1111-1111-1111-111111111111.htm", "GUID-11111111-1111-1111-1111-111111111111", "Draws lines.", [], "2027", "command")
        result = crawler.match_topics({"name":"LINE","type":"command"}, [t1])
        self.assertEqual(result.status, "matched")
        t2 = crawler.Topic("LINE", "LINE (Command)", "https://help.autodesk.com/b/GUID-22222222-2222-2222-2222-222222222222.htm", "GUID-22222222-2222-2222-2222-222222222222", None, [], "2026", "command")
        self.assertEqual(crawler.match_topics({"name":"LINE","type":"command"}, [t1,t2]).status, "ambiguous")

class SourceAdapterTests(unittest.TestCase):
    def test_candidate_versions_and_subreleases(self):
        meta={"version_axes":{"system_variable":["2017","2017.1","2018","2018.1","2019","2020","2020.1","2021"]}}
        r={"type":"system_variable","availability":[{"from":"2017.1","to":"2020.1"}],"new_in":["2017.1"],"changed_in":["2020.1"]}
        versions=crawler.candidate_versions(r,meta)
        self.assertEqual(versions[0],"2020")
        self.assertEqual(len(versions),len(set(versions)))

class HttpClientTests(unittest.TestCase):
    def test_cache_prevents_second_network_call(self):
        calls=[]
        def opener(req, timeout):
            calls.append(req.full_url)
            return crawler.FakeResponse(b"hello", 200, {"Content-Type":"text/plain"})
        with tempfile.TemporaryDirectory() as td:
            c=crawler.CachedHttpClient(Path(td),"test-agent",opener=opener,robots=False)
            self.assertEqual(c.get_text("https://help.autodesk.com/x").text,"hello")
            self.assertTrue(c.get_text("https://help.autodesk.com/x").from_cache)
            self.assertEqual(len(calls),1)

if __name__ == "__main__": unittest.main()
