# Autodesk 跨版本命令与系统变量文档抓取设计

日期：2026-07-11

## 1. 目标

为现有生命周期数据中的全部 2608 条记录补充 Autodesk 官方英文文档索引和精简说明：

- Commands：1444 条，保留同名独立记录。
- System Variables：1164 条。
- 每条生命周期记录必须对应一条文档结果记录。
- 找不到 Autodesk 官方主题页时仍输出记录，并明确标记 `not_found`。

现有 `data/autocad_2004_2027.jsonl` 不修改；文档数据独立保存，按 `lifecycle_id` 一对一关联。

## 2. 官方数据源

### 2.1 旧版静态文档

- AutoCAD 2013：`http://docs.autodesk.com/ACD/2013/ENU/`
- AutoCAD 2014：`http://docs.autodesk.com/ACD/2014/ENU/`
- 使用 `contents-data.html` 建立命令和系统变量候选索引。
- 2013 已验证包含 790 个命令主题和 836 个系统变量主题。
- 2014 已验证包含 804 个命令主题和 850 个系统变量主题。

旧站 HTTPS 证书名称失效；只对已验证可访问的官方 HTTP 静态地址发起只读请求。

### 2.2 新版 Autodesk Help

- 产品入口：`https://help.autodesk.com/view/ACD/{version}/ENU/`
- 主题页：`https://help.autodesk.com/cloudhelp/{version}/ENU/.../files/{topic}.htm`
- 官方搜索服务：`https://beehive.autodesk.com/community/service/rest/cloudhelp/resource/cloudhelpchannel/search/`
- 已验证 2018–2027 有 TOC 数据；2015–2017 可通过搜索服务尝试精确查询。
- 2027 命令和系统变量主题已验证在线。

### 2.3 来源限制

- 只使用 Autodesk 官方域名：`docs.autodesk.com`、`help.autodesk.com`、`beehive.autodesk.com`。
- 不使用搜索结果中的论坛、技术支持文章、第三方站点作为匹配主题。
- 搜索结果必须满足 `source=CloudHelp`、标题精确匹配类型后缀，并且 URL 属于 Autodesk CloudHelp。
- 不从 HyperPics 或论坛补正文；它们继续作为生命周期表来源署名存在。

## 3. 抓取覆盖策略

### 3.1 每条生命周期记录都输出

正式文档 JSONL 固定 2608 行。Commands 的同名重复记录不合并，以 `lifecycle_id` 关联原记录；它们允许指向相同 Autodesk 文档主题。

### 3.2 候选版本顺序

针对每条记录，从生命周期可用区间计算查询版本：

1. 优先查询最后一个可用版本。
2. 再按倒序查询 `new_in`、`changed_in` 和其他可用版本点。
3. `2017.1`、`2018.1`、`2020.1` 映射到基础年度版本查询。
4. 2013/2014 静态索引始终作为独立候选来源参与匹配。
5. 同一 GUID/URL 命中后停止重复抓取。

这样可使 2027 新增项目使用 2027 文档，已经移除的项目使用其最后可用版本或 2013/2014 归档。

### 3.3 未找到

在所有候选版本和两个静态索引中均未找到时：

```json
{
  "lifecycle_id": "cmd-0001",
  "type": "command",
  "name": "*SCROLL",
  "match": {
    "status": "not_found",
    "strategy": null,
    "document_version": null
  },
  "documentation": null
}
```

`not_found` 是有效结果，不视为抓取失败。网络请求失败、解析异常和候选冲突必须单独报告，不能伪装成 `not_found`。

## 4. 名称匹配

匹配必须确定性执行，不使用编辑距离或自动模糊匹配。

### 4.1 标准化

- 大小写统一为大写。
- 去掉透明命令前缀 `'`，但保留 `+`、`-`、`*`。
- 规范化连续空白。
- 对 `NAME (ALIAS)` 形式生成主名称和括号别名候选，但不删除其他说明文字。

### 4.2 可靠性顺序

1. Autodesk 页面 `cmdname` / `sysvarname` 与原名完全匹配。
2. 去透明前缀后与页面元数据完全匹配。
3. Autodesk 标题严格等于 `NAME (Command)` 或 `NAME (System Variable)`。
4. 2013/2014 静态索引标题严格匹配。
5. 明确的 `NAME (ALIAS)` 主名或别名严格匹配。

一个生命周期名称命中多个不同主题时输出 `ambiguous`，保留候选 URL，不自动选择。

## 5. 精简提取字段

只提取主题页中的：

- 官方名称：`cmdname` 或 `sysvarname`。
- 页面标题。
- 官方 URL。
- GUID/topic ID。
- 文档版本。
- `meta description` 或搜索结果 `shortDescription`。
- `Summary` 区域的段落文本。

清洗规则：

- 解码 HTML entity。
- 合并连续空白。
- 保留段落顺序。
- 不保存图片、脚本、CSS、导航、完整 HTML、命令提示树或相关主题全文。
- `description` 与完全相同的第一条 Summary 段落去重。

## 6. 数据结构

文件：`data/autodesk_documentation.jsonl`

匹配记录：

```json
{
  "lifecycle_id": "cmd-0234",
  "type": "command",
  "name": "3DSIN",
  "available_in_document_version": true,
  "match": {
    "status": "matched",
    "strategy": "metadata_exact",
    "document_version": "2027"
  },
  "documentation": {
    "official_name": "3DSIN",
    "title": "3DSIN (Command)",
    "url": "https://help.autodesk.com/cloudhelp/2027/ENU/AutoCAD-Core/files/GUID-A28A2118-11C4-49D3-B8E5-A99EE46C1D32.htm",
    "guid": "GUID-A28A2118-11C4-49D3-B8E5-A99EE46C1D32",
    "description": "Imports a 3ds Max (3DS) file.",
    "summary": ["..."]
  }
}
```

`available_in_document_version` 必须根据生命周期版本轴重新计算，不能根据页面存在性猜测。

## 7. 输出文件

新增：

```text
data/autodesk_documentation.jsonl
schema/autodesk_documentation.schema.json
reports/autodesk_documentation_report.json
scripts/crawl_autodesk_documentation.py
scripts/validate_autodesk_documentation.py
tests/test_autodesk_documentation.py
```

更新：

```text
README.md
LICENSE
.gitignore
.github/workflows/validate.yml
```

临时缓存：

```text
.cache/autodesk-docs/
```

缓存目录加入 `.gitignore`，不提交 GitHub。

## 8. 抓取行为

- Python 3.11 标准库实现，不新增运行时依赖。
- User-Agent 包含公开仓库 URL 和用途。
- 启动时读取并检查各官方域名的 `robots.txt`；明确禁止的路径不抓取。
- 默认并发数 4。
- 单请求超时 20 秒。
- 失败最多重试 3 次，指数退避。
- 缓存搜索响应和主题 HTML，支持中断后恢复。
- 原子写入 JSONL 和报告，避免中断留下半成品。
- 提供 `--limit`、`--ids`、`--refresh`、`--workers` 和 `--cache-dir` 参数。
- 首先使用少量代表样本验证端到端流程，再执行 2608 条全量抓取。

## 9. 验证与报告

### 9.1 数据不变量

- 文档结果正好 2608 条。
- Commands 正好 1444 条，System Variables 正好 1164 条。
- 每个生命周期 ID 恰好出现一次。
- `type` 和 `name` 与生命周期记录一致。
- `matched` 必须有 documentation；`not_found` 必须为 null；`ambiguous` 必须有至少两个候选。
- matched URL 必须属于 Autodesk 官方允许域名。
- `new_in` 与生命周期等原字段不在文档结果中重复保存。
- 抓取结果中不出现本地绝对路径、缓存内容或完整 HTML。

### 9.2 报告内容

- matched / not_found / ambiguous 数量。
- 按 `metadata_exact`、`transparent_prefix`、`title_exact`、`alias_exact` 分类数量。
- 按文档版本分类数量。
- 2014 可用但未找到文档的项目。
- 2027 可用但未找到文档的项目。
- 文档版本与生命周期可用性不一致的项目。
- 网络失败、解析失败、重试和缓存命中统计。
- 未匹配名称清单和冲突候选清单。

## 10. 版权和许可证边界

- Autodesk 标题、description 和 Summary 摘录明确标记来源于 Autodesk 官方文档。
- 这些 Autodesk 文本不宣称由本仓库以 CC BY 4.0 再许可。
- `LICENSE` 中把新增文档摘录排除在本仓库数据 CC BY 4.0 授权范围之外，并保留 Autodesk 权利声明。
- 抓取器、验证器和匹配逻辑继续采用 MIT。

## 11. 完成标准

1. 代表样本覆盖旧命令、新命令、已移除命令、系统变量、透明命令和 not_found。
2. 全量抓取输出 2608 条。
3. 所有结构验证和单元测试通过。
4. 原生命周期数据验证仍通过。
5. 报告能够解释每条未匹配和冲突记录。
6. GitHub Actions 同时验证生命周期数据和官方文档数据。
7. 功能分支推送并创建 PR，不直接覆盖 main。
