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

## 文件

- `data/autocad_2004_2027.jsonl`：唯一正式数据文件。
- `metadata.json`：版本轴、颜色语义、来源哈希和统计。
- `schema.json`：单条记录的 JSON Schema。
- `scripts/validate.py`：无第三方依赖的完整验证器。

运行验证：

```powershell
python .\scripts\validate.py
```

预期结果：

```text
PASS records=2608 commands=1444 system_variables=1164 version_cells=66084
```

## 限制

- 数据不包含 Autodesk 官方命令说明、参数、默认值或帮助正文。
- `new_in` 和 `changed_in` 忠实保留来源表标记，不擅自修正连续黄色或已可用后再次黄色等来源情况。
- 白色/灰色只表示不可用；单独查看一个灰色单元格时，不直接猜测它是“尚未引入”还是“已经移除”。`removed_in` 依据相邻版本状态推导；`restored_in` 同时排除黄色 `new` 事件。
- Commands 的版本轴按年度版本排列；System Variables 额外包含 `2017.1`、`2018.1` 和 `2020.1`。




## 许可证

- `data/autocad_2004_2027.jsonl`、`metadata.json` 和 `schema.json`：采用 [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)（CC BY 4.0）。使用或再发布数据时，请保留本 README 中的来源与致谢。
- `scripts/validate.py` 及 README 中的代码示例：采用 MIT License。

详见 [`LICENSE`](LICENSE)。
