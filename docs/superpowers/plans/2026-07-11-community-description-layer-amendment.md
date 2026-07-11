# Community Description Layer Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有第三方生命周期比较层改成以 PDF 为唯一生命周期权威的纯用途描述层。

**Architecture:** 保留现有缓存、robots、精确名称解析和关联项提取；移除版本比较、证据分类和冲突输出。每条目标记录只聚合非空用途描述，并由描述数量确定 `matched/not_found/ambiguous`。

**Tech Stack:** Python 3.11 标准库、JSONL、JSON Schema、unittest、GitHub Actions。

## Global Constraints

- 不修改两个现有正式 JSONL。
- 不使用第三方版本或 obsolete 字段判断生命周期。
- 715条目标及594/121类型计数保持不变。
- 同名 occurrence 可以共享用途说明。
- 只保存公开、精确命中、非空的短描述。

### Task 1: 描述记录模型

- [ ] 先修改测试，要求 `crawl_target` 输出 `description_status/descriptions/related_items`，且不含 `evidence_status/comparisons/conflicts`。
- [ ] 运行测试确认因旧结构失败。
- [ ] 实现最小描述聚合与三种状态。
- [ ] 运行相关测试确认通过。

### Task 2: HyperPics 浏览器访问核验

- [ ] 用 agent-reach/browser User-Agent 读取公开入口和目标页面。
- [ ] 记录是否存在无需登录的用途描述，不绕过登录或会员限制。
- [ ] 只有存在公开描述时才增加来源适配器和失败测试；否则在报告/README 说明不适用于描述补充。

### Task 3: Schema、验证器和报告

- [ ] 先修改验证器测试，拒绝旧冲突字段，要求 matched 有非空 descriptions。
- [ ] 更新严格 Schema、验证器和覆盖率报告。
- [ ] 运行测试确认通过。

### Task 4: 重生成与文档

- [ ] 使用缓存重生成715条数据。
- [ ] 验证 matched/not_found/ambiguous、来源和关联项计数。
- [ ] 更新 README、LICENSE 和 Draft PR 描述。
- [ ] 运行29+测试、三个验证器、`git diff --check` 和现有正式文件不变检查。
- [ ] 提交、推送并确认 GitHub Actions 成功。
