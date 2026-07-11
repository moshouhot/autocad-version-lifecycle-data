# 社区用途描述层设计修订

日期：2026-07-11

## 决策

`data/autocad_2004_2027.jsonl` 从 PDF 颜色语义恢复的生命周期是本项目唯一生命周期权威。CADForum、HyperPics 和其他网站只用于补充命令或系统变量的作用描述，不得修改、否定或重新评级 PDF 生命周期。

## 正式结构

`data/community_documentation.jsonl` 仍固定对应 Autodesk 官方 `not_found` 的715条记录，但每条只保存：

- `lifecycle_id`、`type`、`name`：与生命周期记录一对一关联。
- `description_status`：`matched | not_found | ambiguous`。
- `descriptions`：零条或多条来源描述，每条含 `source`、`url`、`matched_name`、`text`。
- `related_items`：只从描述中的明确 `see NAME`、`exported by NAME` 等关系提取。

删除正式数据中的 `evidence_status`、`comparisons`、`conflicts`、`first_version_text`、`obsolete_text` 和产品可用性字段。第三方版本或停用说法不参与生命周期计算，也不形成冲突状态。

## 同名记录

PDF 中同名但不同 occurrence 的记录继续分别存在。第三方只有一个同名用途说明时，允许多个 occurrence 共享该说明；第三方版本年份不能用于选择、合并或否定 occurrence。

## 来源

- CADForum：715条目标的精确名称端点，提取一句用途描述。
- HyperPics：获准使用普通浏览器 User-Agent 检查公开页面；只有公开且无需登录的用途说明才能进入正式数据。若公开页面只有版本颜色表，不作为用途描述来源。
- 后续来源必须增加独立适配器、来源 URL 和离线夹具，不做模糊名称匹配。

## 报告

`reports/community_cross_validation_report.json` 改为描述覆盖率报告，包含：目标数、matched/not_found/ambiguous、按来源命中数、含关联项记录数、网络/解析错误。不得再出现 lifecycle conflict 数量。

## 完成标准

1. 715条记录，Commands 594、System Variables 121。
2. 生命周期和 Autodesk 官方两个 JSONL 字节级不变。
3. 每个 `matched` 至少有一句非空描述和合规来源 URL。
4. 正式第三方数据不含生命周期比较或冲突字段。
5. README 明确“生命周期以 PDF 为准，第三方只补用途”。
6. 全部测试、三个验证器和 CI 通过，更新现有 Draft PR。
