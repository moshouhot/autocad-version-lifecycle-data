# AutoCAD 2004–2027 命令与系统变量生命周期数据集

[![Validate dataset](https://github.com/moshouhot/autocad-version-lifecycle-data/actions/workflows/validate.yml/badge.svg)](https://github.com/moshouhot/autocad-version-lifecycle-data/actions/workflows/validate.yml)
[![Data: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)
[![Code: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)

这是从 AutoCAD 2004–2027 命令简表和系统变量简表中提炼出的结构化生命周期数据。数据不只是转录表格文字，而是恢复每个命令或系统变量在不同版本中的**可用区间、新增、变更、移除和恢复**语义。

## 来源与致谢

本数据集基于以下公开发布的命令与系统变量版本简表进行结构化整理：

- **增强版作者/发布者：e2002** — [AutoCAD 2004-2027 命令简表（明经 CAD 社区）](https://bbs.mjtd.com/thread-195185-1-1.html)。该发布页说明增强版是在 HyperPics 旧版基础上核查并更新到 AutoCAD 2027。
- **最初版本作者与来源：Lee Ambrosius / HyperPics** — [Resources for the AutoCAD and AutoCAD LT Programs](http://hyperpics.com/)。HyperPics 提供了最初的 AutoCAD Commands 和 System Variables Reference Database。

本仓库中的 JSONL 生命周期结构、状态归一化、区间压缩和验证逻辑属于对上述公开资料的数据工程整理。该数据集不是 Autodesk 官方数据集，与 Autodesk 没有隶属或背书关系；AutoCAD 是 Autodesk, Inc. 的商标。

原始 PDF 不在本仓库中再分发；请通过上述公开发布链接查阅来源。

## 数据规模

- Commands：1,444 条
- System Variables：1,164 条
- 合计：2,608 条
- 已核对版本单元格：66,084 个

正式数据只有一份：`data/autocad_2004_2027.jsonl`。每行是一个独立 JSON 对象，可流式读取。

## 可以解决的问题

- 某个命令或系统变量在指定 AutoCAD 版本是否可用？
- 它在哪个版本首次新增？
- 哪些版本发生过变更？
- 它在哪个版本被移除或恢复？
- AutoCAD 2027 当前仍有哪些命令或系统变量可用？
- 升级或降级 AutoCAD 时，哪些依赖可能出现兼容性问题？

适合用于版本兼容性检查、AutoLISP/CAD 插件迁移、RAG 知识库、AI 工具调用约束和数据分析。

## 已确认的颜色语义

| 原表颜色 | 结构化语义 | 该版本是否可用 |
|---|---|---:|
| 绿色 | `available` | 是 |
| 棕色/橙色 | `changed` | 是 |
| 黄色 | `new` | 是 |
| 白色/灰色 | `not_available` | 否 |

颜色只用于生成数据，正式记录不保存 RGB 值。

- 黄色版本写入 `new_in`。
- 棕色/橙色版本写入 `changed_in`。
- 可用变为不可用时，当前版本写入 `removed_in`。
- 不可用重新变为可用且当前版本不是黄色新增时，写入 `restored_in`。
- `new` 和 `changed` 都属于可用状态。

## 记录示例

```json
{
  "id": "sysvar-0006",
  "type": "system_variable",
  "name": "3DCONVERSIONMODE",
  "availability": [{"from": "2008", "to": "2027"}],
  "new_in": ["2008"],
  "changed_in": [],
  "removed_in": [],
  "restored_in": [],
  "available_in_latest": true,
  "source": {"page": 1, "row": 6}
}
```

`restored_in` 表示一个已经存在过的项目在不可用后重新变为可用。黄色 `new` 是首次新增，因此不会同时记为 `restored_in`；棕色/橙色或绿色在不可用区间后重新出现时才会形成恢复事件。

## 字段说明

| 字段 | 含义 |
|---|---|
| `id` | 全局唯一稳定 ID，命令使用 `cmd-`，系统变量使用 `sysvar-` |
| `type` | `command` 或 `system_variable` |
| `name` | 命令或系统变量名称 |
| `availability` | 按对应版本轴压缩后的连续可用区间 |
| `new_in` | 黄色标记的新增版本 |
| `changed_in` | 棕色/橙色标记的变更版本 |
| `removed_in` | 从可用变为不可用的版本 |
| `restored_in` | 从不可用重新变为可用的版本；排除黄色首次新增 |
| `available_in_latest` | 在对应版本轴最后一个版本（2027）是否可用 |
| `express_tools` | 仅命令记录存在，表示是否属于 Express Tools |
| `occurrence` | 仅同名记录的第二条及以后存在，用于保留原表中的独立记录 |
| `source.page/row` | 来源 PDF 的页码和表格行号，便于回溯 |

版本轴位于 `metadata.json`，判断区间时必须使用版本轴顺序，不要把 `2017.1` 等版本转换为浮点数。

## Python：查询名称和指定版本可用性

```python
import json
from pathlib import Path

root = Path(".")
metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))

with (root / "data/autocad_2004_2027.jsonl").open(encoding="utf-8") as f:
    records = [json.loads(line) for line in f]


def is_available(record, version):
    axis = metadata["version_axes"][record["type"]]
    position = axis.index(version)
    for interval in record["availability"]:
        if axis.index(interval["from"]) <= position <= axis.index(interval["to"]):
            return True
    return False

matches = [r for r in records if r["name"].upper() == "3DOSMODE"]
for record in matches:
    print("2010:", is_available(record, "2010"))
    print("2011:", is_available(record, "2011"))
    print("new:", record["new_in"])
    print("changed:", record["changed_in"])
```

## Python：查找升级到 2027 时不可用的项目

```python
import json

with open("data/autocad_2004_2027.jsonl", encoding="utf-8") as f:
    unavailable = [
        record for line in f
        if not (record := json.loads(line))["available_in_latest"]
    ]

print(len(unavailable))
print([record["name"] for record in unavailable[:20]])
```

## JavaScript：流式读取 JSONL

```javascript
import fs from "node:fs";
import readline from "node:readline";

const input = fs.createReadStream(
  "data/autocad_2004_2027.jsonl",
  "utf8"
);
const lines = readline.createInterface({ input, crlfDelay: Infinity });

for await (const line of lines) {
  const record = JSON.parse(line);
  if (record.type === "command" && record.available_in_latest) {
    console.log(record.name);
  }
}
```

## RAG / AI 使用建议

推荐把每一行 JSONL 作为一个独立文档，并将结构字段动态转成自然语言。例如：

```text
AutoCAD system variable 3DOSMODE is available from 2011 through 2027.
It was new in 2011 and changed in 2015 and 2016.
```

不在数据集中保存固定 `search_text`，原因是它能由结构字段生成，重复保存会增大体积并造成字段不一致。构建向量索引时可将 `name`、`type`、`availability`、`new_in`、`changed_in`、`removed_in` 和 `restored_in` 拼成嵌入文本，同时把原始 JSON 作为 metadata 保存。

## Autodesk 官方文档扩展

`data/autodesk_documentation.jsonl` 为全部 2608 条生命周期记录提供一对一的 Autodesk 官方英文文档结果：

- Commands：1444 条，其中 850 条匹配官方主题，594 条标记为 `not_found`。
- System Variables：1164 条，其中 1043 条匹配官方主题，121 条标记为 `not_found`。
- 总计：1893 条 `matched`，715 条 `not_found`，0 条冲突，0 条网络或解析错误。

抓取器优先查询记录最后可用的 AutoCAD 文档版本，并在需要时回退到其他可用版本。它只接受 `help.autodesk.com` CloudHelp 精确标题结果，不使用论坛、技术支持文章或第三方说明补齐。旧版 `docs.autodesk.com` 的 robots.txt 禁止自动抓取，因此没有绕过该限制；无法从新版官方搜索获取的旧项目保留为 `not_found`。

每条记录只保存生命周期 ID、匹配状态、文档版本、官方名称、标题、URL、GUID、一句话描述和精简 Summary。示例：

```json
{"lifecycle_id":"cmd-0159","type":"command","name":"3DSIN","available_in_document_version":true,"match":{"status":"matched","strategy":"metadata_exact","document_version":"2027"},"documentation":{"official_name":"3DSIN","title":"3DSIN (Command)","url":"https://help.autodesk.com/cloudhelp/2027/ENU/AutoCAD-Core/files/GUID-A28A2118-11C4-49D3-B8E5-A99EE46C1D32.htm","guid":"GUID-A28A2118-11C4-49D3-B8E5-A99EE46C1D32","description":"Imports a 3ds Max (3DS) file.","summary":[]}}
```

重新抓取（会读取 robots.txt，使用本地忽略缓存并支持中断续跑）：

```powershell
python scripts/crawl_autodesk_documentation.py --workers 4
python scripts/validate_autodesk_documentation.py
```

抓取报告位于 `reports/autodesk_documentation_report.json`，包含匹配策略、文档版本、未匹配 ID 和 HTTP 缓存统计。CI 只验证已提交数据，不联网重新抓取。

## 社区资料交叉验证

`data/community_documentation.jsonl` 专门复核 Autodesk 官方结果中的 715 条 `not_found`，不会覆盖生命周期数据或官方文档数据。每条记录仍用 `lifecycle_id` 一对一关联。

本次结果：

- 目标：715 条（Commands 594，System Variables 121）。
- CADForum 精确命中：588 条；仍未找到：127 条。
- `corroborated`：533 条；一个第三方来源与生命周期核心结论一致。
- `single_source`：12 条；第三方有记录，但对应生命周期重复行没有可比较的可用区间。
- `conflict`：43 条；第三方版本或明确的“no longer supported”说法与生命周期表不同。
- `not_found`：127 条。
- `confirmed`：0 条。自动抓取没有获得第二个独立直接来源，因此不把单一来源夸大为确认。
- 从说明中严格提取出 15 条带明确上下文的关联命令/变量证据。

主要第三方来源：

- [CADForum AutoCAD Commands](https://www.cadforum.cz/en/command.asp)
- [CADForum AutoCAD System Variables](https://www.cadforum.cz/en/variable.asp)
- [HyperPics System Variables](http://www.hyperpics.com/system_variables/)

HyperPics 的 HTTP 页面可由普通浏览器访问，但其 `robots.txt` 对本抓取器 User-Agent 返回 403。抓取器遵守该限制，没有更换身份或绕过；121 条变量均明确记录 `hyperpics: robots_denied`。因此当前社区证据主要来自 CADForum，HyperPics 只保留为待人工核查来源和原生命周期表的署名来源。

证据状态含义：

| 状态 | 含义 |
|---|---|
| `confirmed` | 至少两个独立直接来源一致；当前数据中为 0 条 |
| `corroborated` | 一个可靠第三方直接来源与生命周期信息一致 |
| `single_source` | 第三方有记录，但生命周期中没有足够字段可比较 |
| `conflict` | 来源之间存在实质差异，双方说法均保留 |
| `not_found` | 启用的合规来源没有精确命中 |

`obsolete` 不会自动解释为不可用；只有来源明确写出 `no longer supported` 或 `removed` 时才与 `available_in_latest` 比较。冲突是“需要复核”的信号，不是对原数据的自动修正。例如 `BLIPMODE` 同时保留生命周期“2027 可用”和 CADForum “Variable no longer supported!” 两个说法。

### Python：合并三层数据

```python
import json


def read_jsonl(path, key):
    with open(path, encoding="utf-8") as stream:
        return {record[key]: record for line in stream if (record := json.loads(line))}


lifecycle = read_jsonl("data/autocad_2004_2027.jsonl", "id")
official = read_jsonl("data/autodesk_documentation.jsonl", "lifecycle_id")
community = read_jsonl("data/community_documentation.jsonl", "lifecycle_id")

item_id = "sysvar-0015"
print(lifecycle[item_id])
print(official[item_id])
print(community.get(item_id))
```

重新抓取和验证：

```powershell
python scripts/crawl_community_documentation.py --workers 2
python scripts/validate_community_documentation.py
```

缓存位于 `.cache/community-docs/`，不会提交 Git。完整覆盖率、来源状态和冲突 ID 位于 `reports/community_cross_validation_report.json`。CI 只验证已提交结果，不访问第三方网站。
## 文件

- `data/autocad_2004_2027.jsonl`：唯一正式数据文件。
- `metadata.json`：版本轴、颜色语义、来源哈希和统计。
- `schema.json`：单条记录的 JSON Schema。
- `scripts/validate.py`：生命周期数据验证器。
- `data/autodesk_documentation.jsonl`：2608 条 Autodesk 官方文档匹配结果。
- `schema/autodesk_documentation.schema.json`：文档结果 Schema。
- `reports/autodesk_documentation_report.json`：全量抓取报告。
- `scripts/crawl_autodesk_documentation.py`：可恢复的跨版本抓取器。
- `scripts/validate_autodesk_documentation.py`：文档数据验证器。
- `data/community_documentation.jsonl`：715 条第三方交叉验证结果。
- `schema/community_documentation.schema.json`：第三方证据记录 Schema。
- `reports/community_cross_validation_report.json`：覆盖率、冲突与抓取状态报告。
- `scripts/crawl_community_documentation.py`：社区证据抓取器。
- `scripts/validate_community_documentation.py`：第三方证据验证器。

运行验证：

```powershell
python .\scripts\validate.py
python .\scripts\validate_autodesk_documentation.py
python .\scripts\validate_community_documentation.py
```

预期结果：

```text
PASS records=2608 commands=1444 system_variables=1164 version_cells=66084
```

## 限制

- 生命周期主数据不包含 Autodesk 官方命令说明、参数、默认值或帮助正文；官方和社区扩展分别保存在独立 JSONL。
- 社区交叉验证不是 Autodesk 官方结论；127 条仍未找到，43 条冲突需要资料或 AutoCAD 运行时复核。
- `new_in` 和 `changed_in` 忠实保留来源表标记，不擅自修正连续黄色或已可用后再次黄色等来源情况。
- 白色/灰色只表示不可用；单独查看一个灰色单元格时，不直接猜测它是“尚未引入”还是“已经移除”。`removed_in` 依据相邻版本状态推导；`restored_in` 同时排除黄色 `new` 事件。
- Commands 的版本轴按年度版本排列；System Variables 额外包含 `2017.1`、`2018.1` 和 `2020.1`。




## 许可证

- `data/autocad_2004_2027.jsonl`、`metadata.json` 和 `schema.json`：采用 [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)（CC BY 4.0）。使用或再发布数据时，请保留本 README 中的来源与致谢。
- `scripts/validate.py` 及 README 中的代码示例：采用 MIT License。

详见 [`LICENSE`](LICENSE)。
