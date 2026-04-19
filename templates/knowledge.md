---
# ── Frontmatter ──────────────────────────────────────────────
id: knowledge-example
title: Example Knowledge Title
type: knowledge
domain: example_domain        # 大领域：operations-research, physics, cs, economics...
topic: example_topic          # 子话题
tags:
  - example
source_refs:
  - local:author-or-source
confidence: draft             # draft | reviewed | verified
updated_at: 2026-04-01
origin: local_seed            # local_seed | web_research | research_synthesis
review_status: draft          # draft | reviewed | verified
---

<!--
═══════════════════════════════════════════════════════════════════
  scholar-agent 知识卡片模板 — 使用指南

  本模板定义知识卡片的标准结构。根据主题特性选择合适的
  "数学深度模式"，不要强行填充不适用的内容。

  ── 数学深度规则 ─────────────────────────────────────────────

  Mode A — Heavy Math (重度数学)
    触发：运筹学、物理、统计、概率、信息论、控制论、优化、计量经济学
    或查询中明确要求推导/证明/最优解时。
    必须包含：
    ✓ 符号定义（在"模型假设"或"符号"子节中统一定义）
    ✓ 完整推导链：假设 → 目标函数 → 一阶条件 → 最优解 → 二阶条件验证
    ✓ 最终结果用 $\boxed{...}$ 框出
    ✓ 数值示例验证关键公式
    ✓ 公式速查表汇总（表格形式）
    ✓ 敏感性/鲁棒性分析（如适用）

  Mode B — Light Math (轻度数学)
    触发：有定量要素但推导非核心（算法复杂度、容量规划、经济学概念、工程启发式）
    要求：
    ✓ 给出关键公式 + 一句话直觉解释
    ✓ 跳过完整推导
    ✓ 用对比表格或图示代替证明
    ✗ 不需要二阶条件验证

  Mode C — No Math (无数学)
    触发：纯定性主题（历史、哲学、管理学、文学分析、定性方法）
    要求：
    ✓ 零公式块
    ✓ 用表格、对比框架、流程图等非数学形式组织
    ✓ 单个数字嵌入正文，不创建公式环境

  ── 自动检测启发式 ─────────────────────────────────────────
    查询或证据含方程、希腊字母、优化语言（min/max/最优/边际）→ Mode A
    含数字、指标、阈值但无方程 → Mode B
    其他 → Mode C

═══════════════════════════════════════════════════════════════════
-->

# 卡片标题

> **知识卡片** | scholar-agent
>
> 主要参考：Author (Year), Author2 (Year)

---

## 目录

1. [第一节](#第一节)
2. [第二节](#第二节)
3. [公式速查表](#公式速查表)（仅 Mode A）
4. [参考文献](#参考文献)

---

## 第一节

[按主题组织内容。使用 ### 子标题细分层级。]

### 1.1 模型假设 / 前提条件 / 符号定义

[Mode A：统一定义所有符号。Mode B/C：列出关键假设即可。]

### 1.2 核心内容

[根据数学深度选择合适的形式：

  Mode A：完整推导链（假设→目标函数→一阶条件→最优解→二阶条件验证），
          用 $\boxed{...}$ 标记最终结果。
  Mode B：关键公式 + 直觉解释 + 对比表格/图示。
  Mode C：表格、对比框架、流程图、叙事分析。
  
  不要勉强填充不适用的形式。]

### 1.3 数值示例 / 具体案例

[Mode A 必须。Mode B 推荐。Mode C 可选——用案例故事代替数值验证。]

---

## 第二节

[继续按需组织更多主题章节。每个大章节用 ## 标题。]

---

## 公式速查表

[仅 Mode A。汇总本卡片涉及的所有关键公式，表格形式。]

| 模型/方法 | 核心公式 | 条件/备注 |
|:--|:--|:--|
| ... | ... | ... |

---

## 参考文献

1. [Title or Description](https://example.com/source1)
2. [Title or Description](https://example.com/source2)

---

## See Also

- [[card-id]] — 简要说明关联原因

---

*文档生成时间：YYYY年MM月DD日*
*版本：v1.0 | scholar-agent 知识卡片*
