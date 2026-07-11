# Autodesk Cross-Version Documentation Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 1444 条 AutoCAD Commands 和 1164 条 System Variables 生成一对一、跨版本、仅来自 Autodesk 官方文档的精简文档 JSONL，并对未找到项目给出可审计的 `not_found` 结果。

**Architecture:** 使用 Python 3.11 标准库构建分层抓取器：HTTP/robots/缓存层、2013/2014 静态索引适配器、Autodesk Beehive 跨版本搜索适配器、主题页解析器、确定性名称匹配器、2608 条生命周期关联与报告输出层。先执行离线单元测试，再执行 7 条在线样本，最后利用缓存跑全量并生成独立数据、Schema 和报告。

**Tech Stack:** Python 3.11 标准库（`urllib`, `html.parser`, `robotparser`, `json`, `hashlib`, `concurrent.futures`, `unittest`），JSON Lines，GitHub Actions。

## Global Constraints

- 正式文档结果必须正好 2608 条：Commands 1444，System Variables 1164。
- 每个 `data/autocad_2004_2027.jsonl` 生命周期 ID 恰好出现一次。
- 仅抓取 `docs.autodesk.com`、`help.autodesk.com`、`beehive.autodesk.com` 的官方内容。
- 不使用论坛、技术支持文章、HyperPics 或其他第三方正文补齐。
- 找不到 Autodesk 官方主题页时输出 `not_found`，不伪造说明。
- 不使用编辑距离或自动模糊匹配。
- 不修改现有生命周期 JSONL。
- Autodesk 标题、description、Summary 摘录不纳入仓库 CC BY 4.0 再许可。
- 默认并发不超过 4；超时 20 秒；最多重试 3 次；遵守 robots.txt。
- 缓存目录 `.cache/autodesk-docs/` 不提交 Git。

---

## File Structure

- Create: `scripts/crawl_autodesk_documentation.py` — HTTP、缓存、解析、匹配、CLI 和输出编排。
- Create: `scripts/validate_autodesk_documentation.py` — 文档数据与生命周期一对一一致性验证。
- Create: `tests/test_autodesk_documentation.py` — 离线解析、匹配、缓存和输出测试。
- Create: `tests/fixtures/autodesk_2014_3dsin.html` — 精简旧版命令页夹具。
- Create: `tests/fixtures/autodesk_2027_sysvar.html` — 精简新版系统变量页夹具。
- Create: `tests/fixtures/beehive_search.json` — 精简官方搜索响应夹具。
- Create: `schema/autodesk_documentation.schema.json` — 单条文档结果 Schema。
- Generate: `data/autodesk_documentation.jsonl` — 2608 条正式结果。
- Generate: `reports/autodesk_documentation_report.json` — 抓取和匹配报告。
- Modify: `.gitignore` — 忽略 `.cache/autodesk-docs/`。
- Modify: `.github/workflows/validate.yml` — 增加单元测试和文档数据验证。
- Modify: `README.md` — 增加文档数据用途、字段和运行方法。
- Modify: `LICENSE` — 排除 Autodesk 摘录的 CC BY 再许可。

### Task 1: HTML 和搜索响应解析器

**Files:**
- Create: `tests/test_autodesk_documentation.py`
- Create: `tests/fixtures/autodesk_2014_3dsin.html`
- Create: `tests/fixtures/autodesk_2027_sysvar.html`
- Create: `tests/fixtures/beehive_search.json`
- Create: `scripts/crawl_autodesk_documentation.py`

**Interfaces:**
- Produces: `parse_topic_html(html: str, url: str, version: str) -> Topic`
- Produces: `parse_search_response(payload: dict, expected_type: str) -> list[SearchEntry]`
- `Topic` fields: `official_name`, `title`, `url`, `guid`, `description`, `summary`, `document_version`, `topic_type`。

- [ ] **Step 1: 编写旧版 3DSIN 解析失败测试**

```python
def test_parse_2014_command_topic():
    html = fixture("autodesk_2014_3dsin.html")
    topic = crawler.parse_topic_html(html, OLD_URL, "2014")
    assert topic.topic_type == "command"
    assert topic.official_name == "3DSIN"
    assert topic.description == "Imports a 3ds Max (3DS) file."
    assert topic.summary == [
        "Data that can be imported from a 3ds Max file includes meshes and materials.",
        "You choose a file to import in the 3D Studio File Import dialog box.",
    ]
```

- [ ] **Step 2: 运行测试并确认因模块不存在失败**

Run: `python -m unittest tests.test_autodesk_documentation.DocumentParserTests.test_parse_2014_command_topic -v`

Expected: FAIL，`crawl_autodesk_documentation` 或 `parse_topic_html` 不存在。

- [ ] **Step 3: 实现 Topic 与定向 HTMLParser**

实现以下公开签名：

```python
@dataclass(frozen=True)
class Topic:
    official_name: str
    title: str
    url: str
    guid: str
    description: str | None
    summary: list[str]
    document_version: str
    topic_type: str


def parse_topic_html(html: str, url: str, version: str) -> Topic:
    parser = AutodeskTopicParser()
    parser.feed(html)
    name = parser.meta.get("cmdname") or parser.meta.get("sysvarname")
    topic_type = parser.meta.get("topic-subtype")
    if topic_type not in {"command", "systemvariable"} or not name:
        raise ParseError("not a command or system-variable topic")
    summary = dedupe_paragraphs(parser.summary, parser.meta.get("description"))
    return Topic(
        official_name=normalize_space(name),
        title=normalize_space(parser.title),
        url=url,
        guid=extract_guid(url, parser.meta.get("topicid")),
        description=optional_space(parser.meta.get("description")),
        summary=summary,
        document_version=version,
        topic_type="command" if topic_type == "command" else "system_variable",
    )
```

解析器只在 `h2` 文本为 `Summary` 后采集 `p`，遇到下一个 `h2` 或 Summary 容器结束时停止；跳过 script/style/navigation。

- [ ] **Step 4: 增加新版系统变量和搜索响应测试**

测试 `sysvarname`、HTML entity、重复 description/Summary 去重，以及搜索响应只保留：

```python
entry.source == "CloudHelp"
entry.url.startswith("https://help.autodesk.com/cloudhelp/")
entry.title.endswith("(Command)") or entry.title.endswith("(System Variable)")
```

- [ ] **Step 5: 实现 `parse_search_response` 并运行全部解析测试**

Run: `python -m unittest tests.test_autodesk_documentation.DocumentParserTests -v`

Expected: PASS。

### Task 2: 名称标准化和确定性匹配

**Files:**
- Modify: `tests/test_autodesk_documentation.py`
- Modify: `scripts/crawl_autodesk_documentation.py`

**Interfaces:**
- Produces: `name_candidates(name: str) -> list[tuple[str, str]]`
- Produces: `match_topics(record: dict, topics: list[Topic]) -> MatchResult`
- `MatchResult.status`: `matched | not_found | ambiguous`

- [ ] **Step 1: 编写名称标准化失败测试**

覆盖：

```python
assert name_candidates("'-ACTSTOP") == [("-ACTSTOP", "transparent_prefix")]
assert name_candidates("-3DCONFIG") == [("-3DCONFIG", "exact")]
assert name_candidates("AUTOCOMPLETE (INPUTSEARCHOPTIONS)") == [
    ("AUTOCOMPLETE (INPUTSEARCHOPTIONS)", "exact"),
    ("AUTOCOMPLETE", "alias_primary"),
    ("INPUTSEARCHOPTIONS", "alias_parenthetical"),
]
```

- [ ] **Step 2: 运行并确认失败，然后实现标准化**

只做大小写、空白、透明前缀和明确括号别名处理；不得删除 `+/-/*`。

- [ ] **Step 3: 编写匹配优先级和冲突测试**

必须证明：metadata exact 优先于 title exact；同一 URL/GUID 去重；两个不同 GUID 同优先级命中时返回 `ambiguous`；无命中返回 `not_found`。

- [ ] **Step 4: 实现 `match_topics` 并运行测试**

Run: `python -m unittest tests.test_autodesk_documentation.NameMatchingTests -v`

Expected: PASS。

### Task 3: HTTP、robots、缓存和重试层

**Files:**
- Modify: `tests/test_autodesk_documentation.py`
- Modify: `scripts/crawl_autodesk_documentation.py`

**Interfaces:**
- Produces: `CachedHttpClient(cache_dir: Path, user_agent: str, timeout: float, retries: int)`
- Produces: `get_text(url: str, refresh: bool = False) -> HttpResult`
- Produces: `get_json(url: str, refresh: bool = False) -> tuple[dict, HttpResult]`

- [ ] **Step 1: 用本地 fake opener 编写缓存和重试失败测试**

测试第一次写缓存、第二次不访问网络、临时 503 后重试、404 不重试、robots 禁止时抛 `RobotsDenied`、缓存文件中不包含本地绝对路径。

- [ ] **Step 2: 运行失败测试并实现最小客户端**

缓存键：`sha256(url.encode()).hexdigest()`；缓存元数据只写 URL、状态码、抓取时间和正文文件名。写入使用临时文件加 `replace()` 原子提交。

退避：第 1/2/3 次失败前等待 `1/2/4` 秒；测试中注入 `sleep` 以避免真实等待。

- [ ] **Step 3: 运行 HTTP 层测试**

Run: `python -m unittest tests.test_autodesk_documentation.HttpClientTests -v`

Expected: PASS。

### Task 4: 旧版索引和 Beehive 搜索适配器

**Files:**
- Modify: `tests/test_autodesk_documentation.py`
- Modify: `scripts/crawl_autodesk_documentation.py`

**Interfaces:**
- Produces: `parse_legacy_index(html: str, version: str) -> dict[tuple[str, str], list[TopicRef]]`
- Produces: `search_url(name: str, item_type: str, version: str) -> str`
- Produces: `candidate_versions(record: dict, metadata: dict) -> list[str]`

- [ ] **Step 1: 编写静态索引解析和版本顺序失败测试**

验证 2013/2014 `(Command)` 与 `(System Variable)` 标题；验证 `2017.1 -> 2017`、`2018.1 -> 2018`、`2020.1 -> 2020`；候选版本以最后可用版本开始并去重。

- [ ] **Step 2: 实现旧索引解析和搜索 URL**

搜索查询固定为：

```python
suffix = "Command" if item_type == "command" else "System Variable"
query = f"{candidate_name} ({suffix})"
params = {
    "origin": "upi", "p": "ACD", "v": version, "l": "ENU",
    "maxresults": "100", "q": query, "source": "CloudHelp",
}
```

- [ ] **Step 3: 实现候选版本并运行适配器测试**

Run: `python -m unittest tests.test_autodesk_documentation.SourceAdapterTests -v`

Expected: PASS。

### Task 5: 单记录解析与 CLI 编排

**Files:**
- Modify: `tests/test_autodesk_documentation.py`
- Modify: `scripts/crawl_autodesk_documentation.py`

**Interfaces:**
- Produces: `resolve_record(record, metadata, sources, client) -> dict`
- Produces CLI: `python scripts/crawl_autodesk_documentation.py [options]`

- [ ] **Step 1: 编写 matched/not_found/ambiguous 输出测试**

输出只能包含：`lifecycle_id`, `type`, `name`, `available_in_document_version`, `match`, `documentation`；不复制生命周期区间和事件字段。

- [ ] **Step 2: 实现单记录解析**

顺序：复用同名解析缓存 → 查 2013/2014 索引 → 按候选版本调用 Beehive → 过滤精确标题 → 抓主题页 → 用元数据二次确认 → 匹配 → 计算 `available_in_document_version`。

- [ ] **Step 3: 实现 CLI 参数**

```text
--input data/autocad_2004_2027.jsonl
--metadata metadata.json
--output data/autodesk_documentation.jsonl
--report reports/autodesk_documentation_report.json
--cache-dir .cache/autodesk-docs
--workers 4
--limit N
--ids cmd-0159,sysvar-0017
--refresh
```

`--limit/--ids` 默认写到显式指定的临时输出，禁止覆盖正式 2608 行文件；全量成功后原子替换正式文件。

- [ ] **Step 4: 实现稳定顺序和报告统计并运行编排测试**

Run: `python -m unittest tests.test_autodesk_documentation.OrchestrationTests -v`

Expected: PASS。

### Task 6: Schema 和独立验证器

**Files:**
- Create: `schema/autodesk_documentation.schema.json`
- Create: `scripts/validate_autodesk_documentation.py`
- Modify: `tests/test_autodesk_documentation.py`

**Interfaces:**
- Consumes: 生命周期 JSONL、文档 JSONL、报告、Schema。
- Produces: 退出码 0 和摘要：`PASS documentation records=2608 commands=1444 system_variables=1164 ...`

- [ ] **Step 1: 编写验证器 RED 测试**

验证缺行、重复 ID、type/name 不一致、matched 无文档、not_found 带文档、非 Autodesk URL、ambiguous 少于两个候选、文档版本不在合法年度、错误可用性计算、遗留 HTML/本地路径字段。

- [ ] **Step 2: 实现 Schema 和无第三方依赖验证器**

Schema 使用 Draft 2020-12，`additionalProperties=false`。验证器必须逐行对照生命周期源，并重新计算文档版本可用性。

- [ ] **Step 3: 运行全部离线测试**

Run: `python -m unittest discover -s tests -v`

Expected: 全部 PASS。

### Task 7: 在线代表样本抓取

**Files:**
- Generate temporary ignored cache/output only。

**Interfaces:**
- Uses IDs: `cmd-0159`, `sysvar-0017`, `sysvar-0015`, `cmd-0015`, `cmd-0001`, `cmd-0872`, `cmd-0024`。

- [ ] **Step 1: 检查 robots.txt 和官方端点**

Run crawler with the 7 IDs and `--output .cache/autodesk-docs/pilot.jsonl --report .cache/autodesk-docs/pilot-report.json`。

Expected:

- `3DSIN` matched。
- `ACTIVITYINSIGHTSSTATE` matched 2024–2027 文档之一。
- `ACISOUTVER` 优先尝试最后可用版本，允许 2013/2014 归档匹配或 not_found。
- `'-ACTSTOP` 通过透明前缀匹配。
- `*SCROLL` 允许 not_found。
- `LINE` 精确匹配，不被泛搜索结果误导。
- `-BCONVERT` 尝试 2025 文档。

- [ ] **Step 2: 审核 7 条输出和 HTTP 统计**

网络错误、解析错误或错误匹配必须先修复并重新运行离线测试；不得直接开始全量。

### Task 8: 全量抓取与 2608 条验证

**Files:**
- Generate: `data/autodesk_documentation.jsonl`
- Generate: `reports/autodesk_documentation_report.json`

- [ ] **Step 1: 执行全量抓取**

Run:

```powershell
python scripts/crawl_autodesk_documentation.py --workers 4
```

Expected: 原子生成 2608 行；中断可复用缓存续跑。

- [ ] **Step 2: 执行文档数据验证**

Run:

```powershell
python scripts/validate_autodesk_documentation.py
python scripts/validate.py
```

Expected: 两个验证器均 PASS。

- [ ] **Step 3: 审核报告**

确认 matched/not_found/ambiguous 总和为 2608，Commands/System Variables 分项正确；网络/解析失败为 0，或每个失败均有明确列表且重新运行后稳定复现。

### Task 9: README、许可证和 CI

**Files:**
- Modify: `README.md`
- Modify: `LICENSE`
- Modify: `.gitignore`
- Modify: `.github/workflows/validate.yml`

- [ ] **Step 1: 更新 README**

说明跨版本来源、数据结构、`not_found`、官方 URL、查询示例、重新抓取命令和报告统计；明确 Autodesk 摘录来源和非官方关系。

- [ ] **Step 2: 更新许可证边界**

明确 `data/autodesk_documentation.jsonl` 中 Autodesk 标题、description 和 Summary 不包含在 CC BY 4.0 授权中；抓取器和验证器采用 MIT。

- [ ] **Step 3: 更新 CI**

Workflow 顺序：生命周期验证 → `unittest discover` → 文档数据验证。CI 不联网、不重新抓取。

- [ ] **Step 4: 最终验证和秘密扫描**

Run:

```powershell
python -m unittest discover -s tests -v
python scripts/validate.py
python scripts/validate_autodesk_documentation.py
```

检查无 `.cache`、HTML、PDF、绝对路径、token 或临时输出进入 Git。

### Task 10: 提交、推送与 PR

**Files:** all intended feature files only。

- [ ] **Step 1: 检查 diff 和提交范围**

Run: `git status -sb`, `git diff --stat`, `git diff --check`。

- [ ] **Step 2: 提交实现与数据**

Commit message: `Add cross-version Autodesk documentation index`。

- [ ] **Step 3: 推送功能分支**

Run: `git push -u origin codex/crawl-autodesk-docs`。

- [ ] **Step 4: 创建 Draft PR**

Title: `[codex] add cross-version Autodesk documentation index`。

PR body 包含抓取来源、2608 条覆盖、matched/not_found/ambiguous 统计、测试、缓存未提交、许可证边界和已知限制。

## Plan Self-Review

- Spec coverage: 2608 条覆盖、跨版本官方来源、not_found、确定性匹配、精简字段、缓存/robots/重试、报告、许可证和 PR 均有对应任务。
- Placeholder scan: 未发现占位符或未完成步骤。
- Type consistency: `Topic`, `SearchEntry`, `MatchResult`, `HttpResult` 与 CLI/验证器字段名称一致。
- Critical path: 离线解析 → 匹配 → HTTP → 来源适配 → 编排 → Schema → pilot → full crawl → docs/CI → PR。
- Scope: 单一抓取与文档索引子系统，无需再拆分。
