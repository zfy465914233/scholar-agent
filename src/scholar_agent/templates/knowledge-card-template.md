# Knowledge 卡标准模板（Knowledge Card Standard Template）

> 版本 v1.0 | 2026-06
> 对应标准：`scholar-agent/references/knowledge-quality-standard.md` 八维标准
> 适用工具：`save_research` / `build_knowledge_card`（`close_knowledge_loop.py`）
> 用途：本文件是 knowledge 卡的**结构说明文档**，不是会被渲染的占位模板。调 `save_research` / `build_knowledge_card` 时，按下方 frontmatter 字段与章节结构组织 `answer_json`。

---

## 一、frontmatter 字段（全字段含义）

frontmatter 由 `_build_frontmatter`（`close_knowledge_loop.py`）生成。字段分三类：**必填**、**时效**（G4）、**自动**。

### 必填字段（内容标准）

| 字段 | 含义 | 示例 | 来源 |
|:--|:--|:--|:--|
| `id` | 卡唯一标识（slug） | `bayesian-optimization-basics` | `_resolve_card_metadata` |
| `title` | 卡标题（`标签 — query`） | `知识卡片 — 什么是贝叶斯优化` | note_label + query |
| `type` | 卡类型 | `knowledge` / `method` / `engineering` | answer_data.card_type |
| `domain` | 主领域 | `machine-learning` | domain 分流 |
| `topic` | 细分主题 | `bayesian-optimization` | meta.topic |
| `tags` | 检索/关联标签（列表） | `bo`, `surrogate-model` | `_collect_tags` |
| `source_refs` | 一手出处 URL（列表，≤10） | arXiv / 官网 | `collect_source_urls` |
| `confidence` | 准确性置信度 | `confirmed` / `draft` / `low` | answer_data / 参数 |

### 时效字段（G4 实时性 + 可演进）

| 字段 | 含义 | 示例 | 计算逻辑 |
|:--|:--|:--|:--|
| `source_date` | 最早源年份（单值，F4） | `2024` | `_extract_source_year` |
| `source_years` | 源年份覆盖范围 | `2022~2026` / `2024` / `unknown` | `_format_source_years`（min~max） |
| `updated_at` | 最近更新日期 | `2026-06-18` | 创建/更新时间 |
| `created_at` | 创建日期 | `2026-06-18` | 创建时间 |
| `info_freshness` | 一句话时效描述 + 复核建议 | `覆盖到 2024；该领域变化较快，建议每 6 个月复核一次` | `_build_info_freshness` |
| `version` | 卡版本号（新建 = 1.0） | `"1.0"` | 固定，增量更新时 bump |

> **source_years 规则**：单源 → `"2024"`；多源 → `"2022~2026"`；无年份 → `"unknown"`。
> **info_freshness 规则**：AI/ML/LLM 等快变领域（阈值 ≤1y）→「变化较快，建议每 6 个月复核」；其余 →「变化较慢，建议定期复核」。
> **version 规则**：新建卡固定 `"1.0"`；后续局部刷新（如只更新过期 section）bump 到 `"1.1"`、`"2.0"`。

### 自动字段（系统）

| 字段 | 含义 |
|:--|:--|
| `origin` | 来源管道（固定 `web_research_with_synthesis`） |
| `review_status` | 审核状态（新建 = `draft`） |
| `language` | 卡语言（`zh` / `en`） |

---

## 二、标准章节结构

卡正文由 `_build_toc` + `_build_body_sections` 渲染，章节固定。调 `save_research` 时，`answer_json` 的 key 与章节一一对应：

| 章节 | answer_json key | 内容要求（八维映射） |
|:--|:--|:--|
| **问题** | （query） | 一句话定义要解决的具体场景 |
| **回答** | `answer` | 主回答；详实性——一手原文 inline，看卡不用查网 |
| **支撑论据** | `supporting_claims` | 每条带 `claim` + `evidence_ids` + `confidence`；可溯源 |
| **推论** | `inferences` | 从论据推出的结论 |
| **不确定性** | `uncertainty` | 存疑点显式标注（准确性） |
| **缺失证据** | `missing_evidence` | 还差什么一手资料 |
| **下一步** | `suggested_next_steps` | action 部分——可执行步骤 / 决策（可用性） |
| **出处** | `sources` | source_refs 渲染成的出处网 |

> 可用性强的卡（method/engineering 型）可附加：`prerequisites` / `implementation_steps` / `verification` / `pitfalls` / `rollback` / `expected_output` / `example`。

---

## 三、调 save_research 时的组织方式

```python
answer_json = {
    "answer": "...主回答（带一手原文片段、数字、机制）...",
    "supporting_claims": [
        {"claim": "...", "evidence_ids": ["e1"], "confidence": "high"},
    ],
    "inferences": ["..."],
    "uncertainty": ["..."],
    "missing_evidence": ["..."],
    "suggested_next_steps": ["...可执行步骤..."],
    "sources": ["https://...", "https://arxiv.org/abs/..."],
    "language": "zh",
}
```

frontmatter 的 `source_date` / `source_years` / `info_freshness` / `version` 由 `build_knowledge_card` **自动**从 answer + sources 推导，**无需手动传**。若 answer/sources 文本中含明确的 4 位年份（如 `Smith (2024)`）或 arxiv id（如 `2401.12345`），时效字段会被自动填充。

---

## 四、质量自检（对照八维）

- [ ] 准确性：每条数字锚了 source？`confidence` 分级了？
- [ ] 实时性：`source_years` 非空？快变领域是否标注「定期复核」？
- [ ] 详实性：看卡能独立解答，不用再查网？一手原文 inline 了？
- [ ] 可用性：`suggested_next_steps` 是可执行 action，不是纯描述？
- [ ] 可溯源：`source_refs` 非空？易失效源（招聘 JD 等）信息已归纳进卡？
- [ ] 可演进：`version` 标了？

> 校验工具：`knowledge_lifecycle.validate_card_quality`（八维质量门，含 stale 检测）。
