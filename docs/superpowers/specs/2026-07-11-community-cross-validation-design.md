# AutoCAD 社区资料交叉验证设计

日期：2026-07-11

## 1. 目标与边界

为 Autodesk 官方文档结果中 715 条 `not_found` 记录建立独立、可审计的第三方证据层：Commands 594 条、System Variables 121 条。优先回答“其他可靠网站是否记载过该项目”“用途和版本范围是否与生命周期表一致”。允许通过正文明确提到的关联命令或变量补充上下文，但关联项不能代替目标项的直接证据。

以下文件保持不变：

- `data/autocad_2004_2027.jsonl`：PDF 颜色语义恢复出的生命周期事实。
- `data/autodesk_documentation.jsonl`：Autodesk 官方主题匹配结果。

第三方结果只通过 `lifecycle_id` 关联。冲突同时保留双方说法并标记，不自动覆盖已有数据。

## 2. 方案比较与选择

### 方案 A：只抓 CADForum

端点稳定，命令和变量均有详情页，实现简单；但只能证明一个第三方站点有记载，不能形成多来源确认。

### 方案 B：CADForum 全量 + HyperPics 定向复核 + 关联项证据（采用）

CADForum 作为 715 条记录的统一第一遍来源；HyperPics 主要复核 2004–2013 的变量历史；描述中明确出现的命令/变量作为关联证据。兼顾覆盖率、证据独立性和成本，并能分开直接证据与间接佐证。

### 方案 C：开放式全网聚合

可能提高覆盖率，但来源质量、页面结构和版权边界不一致，名称误匹配风险高且难重现。本阶段不采用；后续只按人工审核增加新适配器。

## 3. 数据来源和证据等级

### 3.1 CADForum

- Commands：`https://www.cadforum.cz/en/command.asp?cmd=NAME`
- System Variables：`https://www.cadforum.cz/en/variable.asp?cmd=NAME`
- 提取：规范名称、简短说明、首次已知版本、obsolete/no longer supported 状态、LT/Core Console 提示、相关 Autodesk Help GUID（若有）。
- URL 参数标准百分号编码，保留 `+`、`-`、`*` 和透明命令前缀语义。

### 3.2 HyperPics

- 变量入口：`https://www.hyperpics.com/system_variables/`
- 主要复核早期版本存在性和颜色历史，不复制整页内容。
- 只保存目标名称、命中状态、来源 URL 和可确定的最早/最晚可用版本摘要。

### 3.3 关联项

只接受页面正文中明确出现、且可在 2608 条生命周期名称表中精确解析的项目。保存关联名称、类型、关系类型、来源 URL 和证据短句。仅凭名称相似、共同前缀或猜测不得生成关联。

## 4. 匹配与判定规则

### 4.1 直接命中

页面必须同时满足：请求成功且不是未找到模板；显示名称标准化后与目标完全相等；页面类型与目标类型相符。标准化仅允许大小写统一、HTML entity 解码、空白合并和透明前缀显式处理；禁止编辑距离或模糊匹配。

### 4.2 证据状态

每条记录取一个总状态：

- `confirmed`：至少两个独立来源直接命中，且与生命周期核心结论一致；关联证据不能充当第二个直接来源。
- `corroborated`：一个可靠第三方直接命中，且用途或版本/obsolete 信息与生命周期无实质冲突。
- `single_source`：一个第三方直接命中，但缺少足够版本信息，无法判断一致性。
- `conflict`：直接来源的版本、是否 obsolete/removed 或含义与生命周期或另一来源实质不同。
- `not_found`：所有启用来源均无合格直接命中。

优先级：`conflict` > `confirmed` > `corroborated` > `single_source` > `not_found`。任何实质冲突不能被多数一致证据掩盖。

### 4.3 一致性比较

- `Since R14`、`Since 2000` 等早于 2004 的说法，只证明项目在数据集边界前已存在，不与“2004 起可用”冲突。
- `Since ≤ R12` 保存为上界表达，不伪造精确首次版本。
- `obsolete` 不自动等同于 `not_available`；仅在来源明确说 no longer supported/removed，且时间与生命周期可用性冲突时形成移除冲突。
- 无法归一化的版本原样保存，机器比较结果为 `unknown`。

例如 `BLIPMODE` 的“Obsolete since 2012”与生命周期“2004–2027 可用”不能直接互相覆盖，应保存冲突候选，等待运行时或更多资料验证 obsolete 是否仍可调用。

## 5. 数据结构

正式文件：`data/community_documentation.jsonl`，每行对应一个 Autodesk `not_found`，固定 715 行。

```json
{
  "lifecycle_id": "sysvar-0015",
  "type": "system_variable",
  "name": "ACISOUTVER",
  "evidence_status": "confirmed",
  "sources": [
    {
      "source": "cadforum",
      "url": "https://www.cadforum.cz/en/variable.asp?cmd=ACISOUTVER",
      "match_status": "matched",
      "matched_name": "ACISOUTVER",
      "description": "Controls the ACIS version used for files exported by ACISOUT",
      "first_version_text": "R14",
      "obsolete_text": "No longer supported"
    },
    {
      "source": "hyperpics",
      "url": "https://www.hyperpics.com/system_variables/",
      "match_status": "matched",
      "matched_name": "ACISOUTVER"
    }
  ],
  "comparisons": [
    {
      "claim": "first_known_version",
      "result": "consistent",
      "detail": "Third-party source places the variable before the dataset boundary."
    }
  ],
  "related_items": [
    {
      "name": "ACISOUT",
      "type": "command",
      "relation": "controlled_command",
      "source_url": "https://www.cadforum.cz/en/variable.asp?cmd=ACISOUTVER",
      "evidence_text": "Controls the ACIS version used for files exported by ACISOUT"
    }
  ],
  "conflicts": []
}
```

结构原则：

- 未抓到的来源也保留 `match_status: not_found`，便于解释尝试范围。
- 不保存完整 HTML、导航、广告或大段正文。
- 描述只保存来源的一句短说明，不生成 AI 改写文本。
- `comparisons` 保存可复算的机器判定，不把推论混入来源事实。
- `conflicts` 指明冲突双方、字段、各自说法和建议验证方式。

## 6. 组件与数据流

```text
scripts/crawl_community_documentation.py
  ├─ 读取 lifecycle + Autodesk not_found 集合
  ├─ CachedHttpClient（域名白名单、robots、缓存、重试）
  ├─ CADForumAdapter
  ├─ HyperPicsAdapter
  ├─ RelatedItemExtractor
  ├─ EvidenceClassifier
  └─ 原子写入 JSONL 和报告

scripts/validate_community_documentation.py
  └─ 校验 715 条一对一关联、Schema、URL、状态和证据不变量
```

顺序：读取 715 个目标 ID；全量访问 CADForum 精确端点；对 121 条变量查询 HyperPics（若为单索引页则只抓一次）；提取短字段和明确关联；独立比较生命周期；分类并原子写入。

## 7. 网络、缓存与错误处理

- Python 标准库实现；默认并发不超过 2。
- 每个域名读取并遵守 `robots.txt`，禁止路径不绕过。
- 超时 20 秒，瞬时失败最多重试 3 次，指数退避。
- 缓存目录 `.cache/community-docs/`，支持续跑且不提交。
- User-Agent 包含公开仓库地址和只读研究用途。
- 网络错误、robots 禁止、解析错误与正常 `not_found` 分开统计；有未解决抓取错误时不得宣称结果完整。
- 先验证 `*SCROLL`、`+CUSTOMIZE`、`ACISOUTVER`、`QAFLAGS`、`BLIPMODE`，再跑全量。

## 8. 输出和报告

新增：

```text
data/community_documentation.jsonl
schema/community_documentation.schema.json
reports/community_cross_validation_report.json
scripts/crawl_community_documentation.py
scripts/validate_community_documentation.py
tests/test_community_documentation.py
tests/fixtures/community/
```

更新：`README.md`、`.gitignore`、`.github/workflows/validate.yml`。

报告包括：715 条类型统计；各来源 matched/not_found/robots_denied/error；五种 evidence status；含关联证据数量；冲突 ID、字段和双方说法；网络/缓存/重试/解析统计；待人工或运行时验证清单。

## 9. 测试策略

按 TDD 用离线夹具覆盖：CADForum 命令/变量/未找到模板和特殊字符 URL；HyperPics 精确匹配与版本单元格；早期版本表达；obsolete 与 removed 不等价；关联提取防子串误匹配；五种 evidence status 及冲突优先级；缓存/robots/重试/原子写入；715 个 ID 与官方 not_found 集合完全相等。

CI 只跑离线测试和已提交数据验证，不联网重抓。

## 10. 版权、署名和发布边界

README 标注 CADForum、HyperPics 和生命周期来源 URL。第三方短说明和版本文字属于来源摘录，不纳入仓库 CC BY 4.0 再许可；代码采用 MIT，仓库生成的匹配状态、比较结果、关系结构和报告元数据按现有许可处理。不镜像完整页面，不提交 HTTP 缓存。

## 11. 完成标准

1. 正式文件正好 715 条：Commands 594、System Variables 121。
2. 每条 ID 恰好对应一个 Autodesk 官方 `not_found`。
3. 两个现有 JSONL 不修改。
4. 来源事实、机器比较和冲突分层。
5. 五个样本端到端可重放。
6. 全部单元测试、三个数据验证器和 GitHub Actions 通过。
7. 功能分支创建 Draft PR，由用户决定是否合并；不直接修改 `main`。
