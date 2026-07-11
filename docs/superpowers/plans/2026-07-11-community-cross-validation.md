# Community Cross-Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Autodesk 官方结果中 715 条 `not_found` 记录生成独立的 CADForum/HyperPics 第三方证据层、关联项证据和冲突报告。

**Architecture:** 沿用现有 Python 标准库抓取器的可缓存、可恢复和原子写入模式，在独立模块中实现 CADForum 与 HyperPics 适配器、确定性名称匹配、版本比较、关联项提取和证据分类。第三方事实、机器比较和冲突分层保存，只通过 `lifecycle_id` 关联现有数据，不修改两个现有 JSONL。

**Tech Stack:** Python 3.11 标准库（`urllib`, `html.parser`, `robotparser`, `json`, `dataclasses`, `concurrent.futures`, `unittest`）、JSON Lines、JSON Schema、GitHub Actions。

## Global Constraints

- 目标集合固定为 `data/autodesk_documentation.jsonl` 中 `match.status == "not_found"` 的 715 条：Commands 594、System Variables 121。
- 不修改 `data/autocad_2004_2027.jsonl` 和 `data/autodesk_documentation.jsonl`。
- CADForum 对 715 条全量查询；HyperPics 只对 121 条系统变量做定向复核。
- 只做确定性精确匹配，不使用编辑距离或模糊匹配。
- 关联项不能代替直接来源，也不能充当 `confirmed` 的第二个来源。
- 状态优先级固定为 `conflict > confirmed > corroborated > single_source > not_found`。
- `obsolete` 不自动等同于生命周期 `not_available`。
- 默认并发数 2、超时 20 秒、最多重试 3 次，并遵守各来源 `robots.txt`。
- HTTP 缓存保存在 `.cache/community-docs/`，不提交 Git。
- CI 只做离线测试和已提交数据验证，不联网重新抓取。
- 第三方短说明和版本文字不纳入仓库 CC BY 4.0 再许可。

---

## File Structure

- Create: `scripts/crawl_community_documentation.py` — 数据模型、解析器、匹配、比较、分类、HTTP、来源适配器、CLI 和原子输出。
- Create: `scripts/validate_community_documentation.py` — 715 条一对一关系、Schema、来源 URL 和状态不变量验证。
- Create: `tests/test_community_documentation.py` — 全部离线单元测试。
- Create: `tests/fixtures/community/cadforum_command.html` — `*SCROLL` 命令页精简夹具。
- Create: `tests/fixtures/community/cadforum_variable.html` — `ACISOUTVER` 变量页精简夹具。
- Create: `tests/fixtures/community/cadforum_not_found.html` — 未找到模板夹具。
- Create: `tests/fixtures/community/hyperpics_variables.html` — 变量版本表精简夹具。
- Create: `schema/community_documentation.schema.json` — 单条证据记录 Schema。
- Generate: `data/community_documentation.jsonl` — 715 条正式第三方证据结果。
- Generate: `reports/community_cross_validation_report.json` — 覆盖率、冲突、错误和缓存统计。
- Modify: `.gitignore` — 忽略 `.cache/community-docs/`。
- Modify: `.github/workflows/validate.yml` — 增加离线测试和第三方数据验证。
- Modify: `README.md` — 说明用途、字段、证据等级、来源与限制。
- Modify: `LICENSE` — 明确排除 CADForum/HyperPics 摘录的 CC BY 再许可。

---

### Task 1: CADForum 与 HyperPics 离线解析器

**Files:**
- Create: `tests/test_community_documentation.py`
- Create: `tests/fixtures/community/cadforum_command.html`
- Create: `tests/fixtures/community/cadforum_variable.html`
- Create: `tests/fixtures/community/cadforum_not_found.html`
- Create: `tests/fixtures/community/hyperpics_variables.html`
- Create: `scripts/crawl_community_documentation.py`

**Interfaces:**
- Produces: `SourceEvidence(source, url, match_status, matched_name, description, first_version_text, obsolete_text, product_notes)`.
- Produces: `cadforum_url(name: str, item_type: str) -> str`.
- Produces: `parse_cadforum_html(html: str, url: str, expected_name: str, expected_type: str) -> SourceEvidence`.
- Produces: `parse_hyperpics_index(html: str, url: str) -> dict[str, SourceEvidence]`.

- [ ] **Step 1: Capture minimal, provenance-labelled fixtures**

Use agent-reach/Jina only to read the five already selected representative pages, then save minimal HTML fragments containing the title/name, Since/obsolete fields and one description. Add a comment at the top of every fixture containing its source URL and capture date; remove navigation, ads and unrelated rows.

- [ ] **Step 2: Write failing URL and CADForum parser tests**

```python
class CadForumParserTests(unittest.TestCase):
    def test_plus_name_is_percent_encoded(self):
        self.assertEqual(
            crawler.cadforum_url("+CUSTOMIZE", "command"),
            "https://www.cadforum.cz/en/command.asp?cmd=%2BCUSTOMIZE",
        )

    def test_command_page_requires_exact_name(self):
        ev = crawler.parse_cadforum_html(
            fixture("cadforum_command.html"), COMMAND_URL, "*SCROLL", "command"
        )
        self.assertEqual(ev.match_status, "matched")
        self.assertEqual(ev.matched_name, "*SCROLL")
        self.assertEqual(ev.first_version_text, "≤ R12")

    def test_not_found_template_is_not_a_match(self):
        ev = crawler.parse_cadforum_html(
            fixture("cadforum_not_found.html"), MISSING_URL, "MISSING", "command"
        )
        self.assertEqual(ev.match_status, "not_found")
```

- [ ] **Step 3: Run tests and confirm RED**

Run: `python -m unittest tests.test_community_documentation.CadForumParserTests -v`

Expected: ERROR/FAIL because `crawl_community_documentation` or parser functions do not exist.

- [ ] **Step 4: Implement minimal models, URL builder and directed HTML parser**

Use `urllib.parse.urlencode({"cmd": name}, quote_via=urllib.parse.quote)` so `+` becomes `%2B`. Implement a targeted `HTMLParser` that records text by stable page labels rather than CSS classes; return `not_found` unless the displayed item name exactly equals the normalized target and the page heading identifies the correct item type.

- [ ] **Step 5: Write failing HyperPics exact-index test**

```python
class HyperPicsParserTests(unittest.TestCase):
    def test_index_keeps_exact_variable_names_and_version_summary(self):
        index = crawler.parse_hyperpics_index(
            fixture("hyperpics_variables.html"), HYPERPICS_URL
        )
        self.assertIn("ACISOUTVER", index)
        self.assertNotIn("ACISOUT", index)
        self.assertEqual(index["ACISOUTVER"].match_status, "matched")
        self.assertEqual(index["ACISOUTVER"].first_version_text, "2004 or earlier")
```

- [ ] **Step 6: Confirm RED, implement HyperPics parser, then run all parser tests**

Run before implementation: `python -m unittest tests.test_community_documentation.HyperPicsParserTests -v`

Expected: FAIL because `parse_hyperpics_index` is missing.

Run after implementation: `python -m unittest tests.test_community_documentation -v`

Expected: all Task 1 tests PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add scripts/crawl_community_documentation.py tests/test_community_documentation.py tests/fixtures/community
git commit -m "Add community source parsers"
```

---

### Task 2: 生命周期版本比较与证据分类

**Files:**
- Modify: `tests/test_community_documentation.py`
- Modify: `scripts/crawl_community_documentation.py`

**Interfaces:**
- Produces: `parse_first_version(text: str | None) -> VersionClaim | None`.
- Produces: `compare_source_to_lifecycle(record: dict, evidence: SourceEvidence, metadata: dict) -> list[Comparison]`.
- Produces: `classify_evidence(sources: list[SourceEvidence], comparisons: list[Comparison], conflicts: list[Conflict]) -> str`.

- [ ] **Step 1: Write failing version interpretation tests**

```python
class VersionComparisonTests(unittest.TestCase):
    def test_early_release_claim_is_consistent_with_2004_boundary(self):
        claim = crawler.parse_first_version("R14")
        self.assertEqual(claim.kind, "exact")
        self.assertLess(claim.sort_key, crawler.parse_first_version("2004").sort_key)

    def test_less_than_r12_remains_an_upper_bound(self):
        claim = crawler.parse_first_version("≤ R12")
        self.assertEqual(claim.kind, "upper_bound")
        self.assertEqual(claim.raw, "≤ R12")

    def test_unknown_text_is_not_invented(self):
        self.assertEqual(crawler.parse_first_version("very old").kind, "unknown")
```

- [ ] **Step 2: Run RED, then implement a fixed release ordering map**

Run: `python -m unittest tests.test_community_documentation.VersionComparisonTests -v`

Expected: FAIL because version functions are missing.

Implementation must use an explicit ordering map for `R12`, `R13`, `R14`, `2000`, `2000i`, `2002`, then integer years. Never convert subreleases to floats.

- [ ] **Step 3: Write failing obsolete and classifier tests**

```python
class EvidenceClassifierTests(unittest.TestCase):
    def test_obsolete_alone_does_not_mean_removed(self):
        comparisons = crawler.compare_source_to_lifecycle(
            AVAILABLE_2004_2027,
            evidence(obsolete_text="Obsolete since 2012"),
            METADATA,
        )
        self.assertFalse(any(c.result == "conflict" for c in comparisons))

    def test_explicit_no_longer_supported_can_conflict(self):
        comparisons = crawler.compare_source_to_lifecycle(
            AVAILABLE_2004_2027,
            evidence(obsolete_text="No longer supported since 2012"),
            METADATA,
        )
        self.assertTrue(any(c.result == "conflict" for c in comparisons))

    def test_conflict_has_highest_priority(self):
        status = crawler.classify_evidence(
            [matched("cadforum"), matched("hyperpics")],
            [consistent_comparison()],
            [conflict("availability")],
        )
        self.assertEqual(status, "conflict")
```

- [ ] **Step 4: Run RED, implement comparisons and all five statuses, then run GREEN**

Run before: `python -m unittest tests.test_community_documentation.EvidenceClassifierTests -v`

Run after: `python -m unittest tests.test_community_documentation.VersionComparisonTests tests.test_community_documentation.EvidenceClassifierTests -v`

Expected after implementation: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add scripts/crawl_community_documentation.py tests/test_community_documentation.py
git commit -m "Add lifecycle evidence classification"
```

---

### Task 3: 关联命令和变量的严格提取

**Files:**
- Modify: `tests/test_community_documentation.py`
- Modify: `scripts/crawl_community_documentation.py`

**Interfaces:**
- Consumes: exact lifecycle name/type pairs.
- Produces: `build_name_catalog(records: list[dict]) -> dict[str, tuple[dict, ...]]`.
- Produces: `extract_related_items(description: str, target: dict, catalog: dict, source_url: str) -> list[RelatedItem]`.

- [ ] **Step 1: Write failing boundary and ambiguity tests**

```python
class RelatedItemTests(unittest.TestCase):
    def test_extracts_acisout_as_controlled_command(self):
        items = crawler.extract_related_items(
            "Controls the ACIS version used for files exported by ACISOUT.",
            {"name": "ACISOUTVER", "type": "system_variable"},
            CATALOG,
            ACISOUTVER_URL,
        )
        self.assertEqual([(x.name, x.type, x.relation) for x in items], [
            ("ACISOUT", "command", "controlled_command")
        ])

    def test_does_not_match_name_substrings(self):
        items = crawler.extract_related_items(
            "The value is customizable.", TARGET, CATALOG, SOURCE_URL
        )
        self.assertEqual(items, [])

    def test_ambiguous_duplicate_name_is_not_guessed(self):
        items = crawler.extract_related_items(
            "See FOO.", TARGET, DUPLICATE_NAME_CATALOG, SOURCE_URL
        )
        self.assertEqual(items, [])
```

- [ ] **Step 2: Run RED, implement token-boundary extraction and relation phrases**

Run: `python -m unittest tests.test_community_documentation.RelatedItemTests -v`

Expected before: FAIL; expected after: PASS.

Only map explicit phrases (`controls ... used by/exported by`, `same as ... command`, `see ...`) to known relation enums. Save the exact source sentence as `evidence_text`.

- [ ] **Step 3: Commit Task 3**

```powershell
git add scripts/crawl_community_documentation.py tests/test_community_documentation.py
git commit -m "Extract explicit related AutoCAD items"
```

---

### Task 4: HTTP 缓存、robots、来源适配器和目标选择

**Files:**
- Modify: `tests/test_community_documentation.py`
- Modify: `scripts/crawl_community_documentation.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `CachedHttpClient(cache_dir, user_agent, timeout=20, retries=3, opener=..., sleep=..., robots=True)`.
- Produces: `select_targets(lifecycle_records: list[dict], official_records: list[dict]) -> list[dict]`.
- Produces: `crawl_target(record: dict, clients: SourceClients, hyperpics_index: dict) -> CommunityRecord`.

- [ ] **Step 1: Write failing target-set and HTTP behavior tests**

```python
class TargetSelectionTests(unittest.TestCase):
    def test_only_official_not_found_records_are_selected(self):
        targets = crawler.select_targets(LIFECYCLE_FIXTURE, OFFICIAL_FIXTURE)
        self.assertEqual([r["id"] for r in targets], ["cmd-0001", "sysvar-0001"])

class HttpClientTests(unittest.TestCase):
    def test_cache_avoids_second_network_call(self):
        client = fake_client(body="ok")
        client.get_text(CADFORUM_URL)
        second = client.get_text(CADFORUM_URL)
        self.assertTrue(second.from_cache)
        self.assertEqual(client.opener_calls, 1)

    def test_robots_denial_is_distinct_from_not_found(self):
        with self.assertRaises(crawler.RobotsDenied):
            denied_client().get_text(CADFORUM_URL)
```

- [ ] **Step 2: Run RED, reuse the official crawler's tested cache pattern, and constrain hosts**

Run: `python -m unittest tests.test_community_documentation.TargetSelectionTests tests.test_community_documentation.HttpClientTests -v`

Expected before: FAIL; expected after implementation: PASS.

Allowed hosts are exactly `www.cadforum.cz`, `cadforum.cz`, `www.hyperpics.com`, `hyperpics.com`. Cache metadata stores URL, status, fetch time and body filename only.

- [ ] **Step 3: Write failing orchestration tests for commands and variables**

```python
class CrawlTargetTests(unittest.TestCase):
    def test_command_uses_cadforum_only(self):
        out = crawler.crawl_target(COMMAND, FAKE_CLIENTS, HYPERPICS_INDEX)
        self.assertEqual([s.source for s in out.sources], ["cadforum"])

    def test_variable_records_both_source_attempts(self):
        out = crawler.crawl_target(VARIABLE, FAKE_CLIENTS, HYPERPICS_INDEX)
        self.assertEqual([s.source for s in out.sources], ["cadforum", "hyperpics"])
```

- [ ] **Step 4: Run RED, implement orchestration and CLI switches, then run GREEN**

CLI options: `--ids`, `--limit`, `--workers` (default 2, maximum 4), `--cache-dir`, `--refresh`, `--output`, `--report`.

Run after: `python -m unittest tests.test_community_documentation -v`

Expected: all tests PASS.

- [ ] **Step 5: Ignore cache and commit Task 4**

Add exactly `.cache/community-docs/` to `.gitignore`, then:

```powershell
git add scripts/crawl_community_documentation.py tests/test_community_documentation.py .gitignore
git commit -m "Add resumable community evidence crawler"
```

---

### Task 5: Schema、验证器与报告不变量

**Files:**
- Create: `schema/community_documentation.schema.json`
- Create: `scripts/validate_community_documentation.py`
- Modify: `tests/test_community_documentation.py`
- Modify: `scripts/crawl_community_documentation.py`

**Interfaces:**
- Produces: `build_report(records: list[dict], stats: dict, targets: list[dict]) -> dict`.
- Produces CLI: `python scripts/validate_community_documentation.py [--data PATH]`.

- [ ] **Step 1: Write failing report and validator tests**

```python
class OutputInvariantTests(unittest.TestCase):
    def test_report_counts_statuses_sources_and_conflicts(self):
        report = crawler.build_report(COMMUNITY_RECORDS, HTTP_STATS, TARGETS)
        self.assertEqual(report["totals"]["records"], len(TARGETS))
        self.assertEqual(report["evidence_statuses"]["conflict"], 1)
        self.assertEqual(report["sources"]["cadforum"]["matched"], 2)
        self.assertEqual(report["conflict_ids"], ["sysvar-0002"])
```

Add validator fixture tests proving duplicate IDs, a non-target ID, a `confirmed` record with one direct source, a `not_found` record with a matched source, and a disallowed host all fail with distinct messages.

- [ ] **Step 2: Run RED, create strict JSON Schema and validator**

Run: `python -m unittest tests.test_community_documentation.OutputInvariantTests -v`

Expected before: FAIL.

Schema uses `additionalProperties: false` at every object level and enums for source names, match statuses, comparison results, evidence statuses, relation types and conflict fields.

- [ ] **Step 3: Implement deterministic report and atomic writers, then run GREEN**

Sort formal output by lifecycle source order; sort `conflict_ids` and error lists by `lifecycle_id`; use temporary sibling files plus `Path.replace()`.

Run: `python -m unittest discover -s tests -v`

Expected: existing 9 official tests plus all community tests PASS.

- [ ] **Step 4: Commit Task 5**

```powershell
git add schema/community_documentation.schema.json scripts/validate_community_documentation.py scripts/crawl_community_documentation.py tests/test_community_documentation.py
git commit -m "Validate community evidence records"
```

---

### Task 6: 在线样本、全量抓取与人工冲突复核

**Files:**
- Generate: `data/community_documentation.jsonl`
- Generate: `reports/community_cross_validation_report.json`

**Interfaces:**
- Consumes crawler and validators from Tasks 1–5.
- Produces the fixed 715-record dataset and reproducible report.

- [ ] **Step 1: Run existing baseline validators before network work**

```powershell
python -m unittest discover -s tests -v
python scripts/validate.py
python scripts/validate_autodesk_documentation.py
```

Expected: all tests PASS; lifecycle output reports 2608 records; official output reports matched 1893 and not_found 715.

- [ ] **Step 2: Use agent-reach web reading to verify current source behavior and robots**

Run `agent-reach doctor --json`, then read CADForum/HyperPics robots and the five sample pages using the skill's web route. Record redirects and parser-impacting differences; do not bypass denied paths.

- [ ] **Step 3: Run five-ID sample crawl**

```powershell
python scripts/crawl_community_documentation.py --ids cmd-0001,cmd-0002,sysvar-0015,sysvar-XXXX,sysvar-YYYY --workers 1 --output .cache/community-sample.jsonl --report .cache/community-sample-report.json
```

Before execution, resolve the exact lifecycle IDs for `*SCROLL`, `+CUSTOMIZE`, `ACISOUTVER`, `QAFLAGS`, and `BLIPMODE` with a local JSONL query and substitute them for the placeholders. Expected: 5 records, no unresolved network/parse errors; each target name exactly matches its requested record.

- [ ] **Step 4: Inspect sample evidence, especially BLIPMODE semantics**

Confirm `ACISOUTVER` has an explicit `ACISOUT` relation and that `BLIPMODE` does not convert plain “obsolete” into removed without explicit support wording. If served HTML differs from fixtures, add a failing regression test first, update only the relevant parser, and rerun all tests.

- [ ] **Step 5: Run full resumable crawl**

```powershell
python scripts/crawl_community_documentation.py --workers 2
```

Expected: exactly 715 records; 594 commands and 121 variables; report has zero unresolved crawl/parse errors. If interrupted, rerun the same command and use cache hits.

- [ ] **Step 6: Run final data validators and inspect conflicts**

```powershell
python scripts/validate.py
python scripts/validate_autodesk_documentation.py
python scripts/validate_community_documentation.py
python -m unittest discover -s tests -v
```

Expected: all PASS. Manually inspect every record listed in `conflict_ids`; verify the report preserves both claims and a source URL.

- [ ] **Step 7: Confirm existing formal JSONL files are unchanged and commit generated data**

```powershell
git diff 074240a --exit-code -- data/autocad_2004_2027.jsonl data/autodesk_documentation.jsonl
git add data/community_documentation.jsonl reports/community_cross_validation_report.json
git commit -m "Add community cross-validation dataset"
```

---

### Task 7: README、许可边界、CI 与 Draft PR

**Files:**
- Modify: `README.md`
- Modify: `LICENSE`
- Modify: `.github/workflows/validate.yml`

**Interfaces:**
- Documents the exact commands and evidence semantics.
- CI invokes all three validators and the full offline test suite.

- [ ] **Step 1: Update README with exact user-facing usage**

Document `data/community_documentation.jsonl`, its 715-record scope, five statuses, join by `lifecycle_id`, source URLs, a Python join example, conflicts not being automatic corrections, and cache/regeneration commands. Keep CADForum/HyperPics facts separate from Autodesk and lifecycle facts.

- [ ] **Step 2: Extend license exclusions**

Add a short section stating CADForum/HyperPics titles, descriptions and version text remain subject to their source owners and are excluded from this repository's CC BY 4.0 grant; matching structure, code and generated comparison metadata retain existing licenses.

- [ ] **Step 3: Extend CI and verify locally**

Add:

```yaml
- name: Run offline unit tests
  run: python -m unittest discover -s tests -v
- name: Validate community documentation data
  run: python scripts/validate_community_documentation.py
```

Then run all commands from Task 6 Step 6 and `git diff --check`. Expected: all pass and no whitespace errors.

- [ ] **Step 4: Scan changed repository files for accidental secrets and caches**

Use `git status --short` and `git diff --cached --name-only`; ensure no `.cache/`, cookies, absolute local paths or full downloaded pages are staged. Run the connected GitHub secret scanner on changed code/config content before publishing.

- [ ] **Step 5: Commit documentation and CI**

```powershell
git add README.md LICENSE .github/workflows/validate.yml
git commit -m "Document community evidence usage"
```

- [ ] **Step 6: Push feature branch and create Draft PR**

Push `feature/community-evidence`, create a Draft PR targeting `main`, include coverage/status counts and validator output, and do not merge. Verify GitHub Actions; if CI fails, use `github:gh-fix-ci` before asking for review.
