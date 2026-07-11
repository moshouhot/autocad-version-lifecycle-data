import sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import crawl_community_documentation as crawler

FIXTURES=Path(__file__).parent/"fixtures"/"community"
def fixture(name): return (FIXTURES/name).read_text(encoding="utf-8")

class CadForumParserTests(unittest.TestCase):
    def test_plus_name_is_percent_encoded(self):
        self.assertEqual(crawler.cadforum_url("+CUSTOMIZE","command"),"https://www.cadforum.cz/en/command.asp?cmd=%2BCUSTOMIZE")
    def test_command_and_variable_descriptions(self):
        cmd=crawler.parse_cadforum_html(fixture("cadforum_command.html"),"https://www.cadforum.cz/en/command.asp?cmd=*SCROLL","*SCROLL","command")
        var=crawler.parse_cadforum_html(fixture("cadforum_variable.html"),"https://www.cadforum.cz/en/variable.asp?cmd=ACISOUTVER","ACISOUTVER","system_variable")
        self.assertEqual(cmd.description,"Internal scrolling function (reset)")
        self.assertEqual(var.description,"Controls the ACIS version used for files exported by ACISOUT")
    def test_not_found_template_is_not_a_description(self):
        ev=crawler.parse_cadforum_html(fixture("cadforum_not_found.html"),"https://www.cadforum.cz/en/command.asp?cmd=MISSING","MISSING","command")
        self.assertEqual(ev.match_status,"not_found")
        self.assertIsNone(ev.description)

class NameCandidateTests(unittest.TestCase):
    def test_transparent_parenthetical_or_and_range_candidates(self):
        self.assertEqual(crawler.name_candidates("'DDCOLOR (COLOR)"),["DDCOLOR","COLOR"])
        self.assertEqual(crawler.name_candidates("SHELL or SH"),["SHELL","SH"])
        self.assertEqual(crawler.name_candidates("ERRNO or *ERRNO"),["ERRNO","*ERRNO"])
        self.assertEqual(crawler.name_candidates("USERI1 - 5"),["USERI1"])
        self.assertEqual(crawler.name_candidates("` ATTACH"),["ATTACH"])
        self.assertEqual(crawler.name_candidates("-FBXEXPOR"),["-FBXEXPOR","-FBXEXPORT"])
        self.assertEqual(crawler.name_candidates("AI_SEND_FEDBACK"),["AI_SEND_FEDBACK","AI_SEND_FEEDBACK"])
        self.assertEqual(crawler.name_candidates("GEOMARKETVISIBILITY"),["GEOMARKETVISIBILITY","GEOMARKERVISIBILITY"])
        self.assertEqual(crawler.name_candidates("ONLINESYNCPROVIDE"),["ONLINESYNCPROVIDE","ONLINESYNCPROVIDER"])
        self.assertEqual(crawler.name_candidates("SUPRESSALERTS"),["SUPRESSALERTS","SUPPRESSALERTS"])
        self.assertEqual(crawler.name_candidates("CHTEXT"),["CHTEXT","CHT"])
        self.assertEqual(crawler.name_candidates("'BACKGROUND (VIEW - 2008)"),["BACKGROUND","VIEW"])
class DescriptionQualityTests(unittest.TestCase):
    def test_redirects_and_placeholders_are_not_purpose_descriptions(self):
        self.assertFalse(crawler.is_substantive_description("see COLOR"))
        self.assertFalse(crawler.is_substantive_description("Description will be added"))
        self.assertTrue(crawler.is_substantive_description("Sets the current drawing color."))
        self.assertEqual(crawler.description_redirect_candidate("(see ADCENTER)"),"ADCENTER")
        self.assertIsNone(crawler.description_redirect_candidate("Sets the current drawing color."))
class ManuSoftParserTests(unittest.TestCase):
    def test_undocumented_command_notes_become_descriptions(self):
        index=crawler.parse_manusoft_commands(fixture("manusoft_commands.html"),crawler.MANUSOFT_COMMANDS_URL)
        self.assertEqual(index["OLDMTEXT"].description,"Runs the R13 MTEXT command.")
        self.assertEqual(index["ENDSV"].source,"manusoft")

class BricsysParserTests(unittest.TestCase):
    def test_explicit_allowlist_urls_only(self):
        self.assertEqual(
            crawler.bricsys_url("AI_PSPACE","command"),
            "https://help.bricsys.com/en-us/document/command-reference/a/ai_pspace-command-express-tools",
        )
        self.assertIsNone(crawler.bricsys_url("UNRESEARCHED","command"))

    def test_exact_command_and_system_variable_purpose_descriptions(self):
        cmd=crawler.parse_bricsys_html(
            fixture("bricsys_command.html"),
            "https://help.bricsys.com/en-us/document/command-reference/a/aidimprec-command",
            "AIDIMPREC","command",
        )
        var=crawler.parse_bricsys_html(
            fixture("bricsys_system_variable.html"),
            "https://help.bricsys.com/en-us/document/system-variable-reference/l/lispinit-system-variable",
            "LISPINIT","system_variable",
        )
        self.assertEqual(cmd.description,"Changes the display precision of dimension text.")
        self.assertEqual(var.description,"Controls if LISP variables and functions are preserved between drawings.")
        self.assertEqual(cmd.source,"bricsys")

    def test_wrong_document_name_is_rejected(self):
        evidence=crawler.parse_bricsys_html(
            fixture("bricsys_command.html"),"https://help.bricsys.com/x","OTHER","command"
        )
        self.assertEqual(evidence.match_status,"not_found")

    def test_express_tools_title_suffix_is_transparent(self):
        html='<h1>AI_PSPACE command (Express Tools)</h1><p class="shortdesc">Switches to the last opened layout in paper space.</p>'
        evidence=crawler.parse_bricsys_html(html,"https://help.bricsys.com/x","AI_PSPACE","command")
        self.assertEqual(evidence.description,"Switches to the last opened layout in paper space.")
class DescriptionRecordTests(unittest.TestCase):
    def test_pdf_lifecycle_is_not_compared_or_copied(self):
        record={"id":"sysvar-0001","type":"system_variable","name":"BLIPMODE","availability":[{"from":"2004","to":"2027"}],"available_in_latest":True}
        source=crawler.SourceEvidence("cadforum","https://www.cadforum.cz/en/variable.asp?cmd=BLIPMODE","matched","BLIPMODE","Controls drawing blips.")
        out=crawler.build_description_record(record,[source],{})
        self.assertEqual(set(out),{"lifecycle_id","type","name","description_status","descriptions","related_items"})
        self.assertEqual(out["description_status"],"matched")
        self.assertEqual(out["descriptions"][0]["text"],"Controls drawing blips.")
        for forbidden in ("availability","evidence_status","comparisons","conflicts","first_version_text","obsolete_text"):
            self.assertNotIn(forbidden,out)
    def test_not_found_and_ambiguous_statuses(self):
        record={"id":"cmd-0001","type":"command","name":"X"}
        missing=crawler.SourceEvidence("cadforum","u","not_found")
        ambiguous=crawler.SourceEvidence("cadforum","u","ambiguous")
        self.assertEqual(crawler.build_description_record(record,[missing],{})["description_status"],"not_found")
        self.assertEqual(crawler.build_description_record(record,[ambiguous],{})["description_status"],"ambiguous")
    def test_same_description_can_be_shared_by_duplicate_occurrences(self):
        source=crawler.SourceEvidence("cadforum","u","matched","TRACE","Creates trace geometry.")
        a=crawler.build_description_record({"id":"cmd-1","type":"command","name":"TRACE","occurrence":1},[source],{})
        b=crawler.build_description_record({"id":"cmd-2","type":"command","name":"TRACE","occurrence":2},[source],{})
        self.assertEqual(a["descriptions"],b["descriptions"])

class RelatedItemTests(unittest.TestCase):
    def test_explicit_relation_only_and_candidate_first_lookup(self):
        class NoItemsDict(dict):
            def items(self): raise AssertionError("catalog-wide scan")
        target={"id":"sysvar-1","name":"ACISOUTVER","type":"system_variable"}
        catalog=NoItemsDict({"ACISOUT":({"id":"cmd-1","name":"ACISOUT","type":"command"},),"ACISOUTVER":(target,),"BLOCK":({"id":"cmd-2","name":"BLOCK","type":"command"},)})
        items=crawler.extract_related_items("Controls files exported by ACISOUT.",target,catalog,"u")
        self.assertEqual([(x.name,x.relation) for x in items],[("ACISOUT","controlled_command")])
        self.assertEqual(crawler.extract_related_items("Not available in Block editor.",target,catalog,"u"),[])

class TargetAndHttpTests(unittest.TestCase):
    def test_only_official_not_found_records_are_selected(self):
        life=[{"id":"cmd-0001"},{"id":"cmd-0002"}]; docs=[{"lifecycle_id":"cmd-0001","match":{"status":"not_found"}},{"lifecycle_id":"cmd-0002","match":{"status":"matched"}}]
        self.assertEqual([r["id"] for r in crawler.select_targets(life,docs)],["cmd-0001"])
    def test_cache_and_host_allowlist(self):
        calls=[]
        def opener(req,timeout): calls.append(req.full_url); return crawler.FakeResponse(b"hello",200,{"Content-Type":"text/plain"})
        with tempfile.TemporaryDirectory() as td:
            client=crawler.CachedHttpClient(Path(td),opener=opener,robots=False)
            client.get_text("https://www.cadforum.cz/en/x"); self.assertTrue(client.get_text("https://www.cadforum.cz/en/x").from_cache)
            self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError): client.get_text("https://example.com/x")

class ReportTests(unittest.TestCase):
    def test_report_is_description_coverage_only(self):
        records=[
          {"lifecycle_id":"cmd-1","type":"command","name":"A","description_status":"matched","descriptions":[{"source":"cadforum","url":"u","matched_name":"A","text":"Does A."}],"related_items":[]},
          {"lifecycle_id":"sysvar-1","type":"system_variable","name":"B","description_status":"not_found","descriptions":[],"related_items":[]},
        ]
        report=crawler.build_report(records,{"cache_hits":1},records,[],{"hyperpics":"Public page contains version table only; descriptions require membership."})
        self.assertEqual(report["description_statuses"],{"matched":1,"not_found":1})
        self.assertEqual(report["sources"],{"cadforum":1})
        self.assertNotIn("conflict_ids",report)
        self.assertNotIn("evidence_statuses",report)

class CommunityValidatorTests(unittest.TestCase):
    def test_matched_requires_nonempty_description_and_old_fields_are_rejected(self):
        from scripts import validate_community_documentation as validator
        valid={"lifecycle_id":"cmd-0001","type":"command","name":"A","description_status":"matched","descriptions":[{"source":"cadforum","url":"https://www.cadforum.cz/en/command.asp?cmd=A","matched_name":"A","text":"Does A."}],"related_items":[]}
        self.assertEqual(validator.validate_record_shape(valid,1),[])
        invalid=dict(valid,conflicts=[])
        self.assertTrue(any("fields mismatch" in x for x in validator.validate_record_shape(invalid,1)))
        empty=dict(valid,descriptions=[])
        self.assertTrue(any("matched without description" in x for x in validator.validate_record_shape(empty,1)))

    def test_bricsys_source_requires_the_bricsys_help_host(self):
        from scripts import validate_community_documentation as validator
        valid={"lifecycle_id":"cmd-0001","type":"command","name":"AIDIMPREC","description_status":"matched","descriptions":[{"source":"bricsys","url":"https://help.bricsys.com/en-us/document/x","matched_name":"AIDIMPREC","text":"Changes dimension precision."}],"related_items":[]}
        self.assertEqual(validator.validate_record_shape(valid,1),[])
        valid["descriptions"][0]["url"]="https://example.com/copied"
        self.assertTrue(any("source host mismatch" in x for x in validator.validate_record_shape(valid,1)))

if __name__=="__main__": unittest.main()
