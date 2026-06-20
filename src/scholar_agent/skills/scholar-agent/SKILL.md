---
name: scholar-agent
description: "严谨执行论文搜索、文献综述、related work、paper search、literature review、survey synthesis、baseline comparison 与研究路线设计。Use when the user asks for papers, SOTA, baselines, related work, or research planning."
argument-hint: "描述研究主题、范围、时间区间与期望产出"
---

# Scholar-Agent

## 适用场景
- 搜索论文、找 benchmark 或 baseline
- 编写文献综述、related work、survey 或阅读清单
- 比较方法、归纳研究脉络、制定研究方向
- 补单篇或批量论文笔记，并要求结果可验收、可追溯

## 核心原则
- 目标是交付可验收产物，不是“调用过工具”或“落了一个 md 文件”。
- 默认 fail-closed。命中 skeleton、placeholder、路径漂移、元数据缺失或结构不达标时，必须显式失败。
- 默认 canary-first。新流程、新模板、新输入策略先做 1 篇样例，通过后再批量。
- 默认 staging-first。论文 note 先写 staging，再验证，再 promote 到正式目录。
- 不允许静默降级为快速摘要、模板骨架或占位笔记；若用户只要快速概览，必须显式声明这不是完整 scholar 流程。

## 状态机流程
1. Scope Contract
- 明确任务类型：找论文、单篇 note、批量 note、综述、研究规划。
- 明确交付标准：完整论文笔记、快速概览、综述卡片，或其中组合。
- 若需求含糊，先澄清，不自行压缩或扩张范围。

2. Inventory
- 先枚举目标论文集合，并记录最少身份信息：title、authors、year、paper id、source type、existing note status。
- 对批量任务，先给出计划中的核心论文集合，再进入生成。

3. Metadata Gate
- 生成完整论文笔记前，至少满足以下最低输入契约之一：
	- `abstract` 或 `summary`
	- 本地 `pdf_path`
	- 可解析的 `arxiv_id` 或等价稳定 paper id
- 若只有 title 和 authors，不允许直接进入完整 note 生成。
- 对批量任务，缺 metadata 的论文进入 blocked 列表，不得混入 batch generation。

4. Canary Generation
- 每次新任务先只生成 1 篇样例。
- 输出必须先写到 staging 目录，例如 `paper-notes/.staging/<job-id>/`。
- 生成后必须运行 `scripts/validate_note.py`；未通过前不得继续批量。

5. Batch Generation
- 仅当 canary 通过验证时，才允许批量执行。
- 批量中每篇都必须独立验证，不允许因为前一篇通过就跳过后续校验。

6. Validation
- 验证是硬门，不是建议。至少检查：
	- skeleton / placeholder / duplicated frontmatter
	- 核心 section 是否存在且有实质内容
	- `unknown` 等占位值是否进入正式内容
	- 关键结论是否带有最小证据锚点或可回溯 source id
	- 路径是否符合 canonical policy
- 推荐使用：
	- 严格校验：`python scripts/validate_note.py --note <path> --paper-type <type> --require-frontmatter --require-evidence --dataset-policy required`
- 有条件回退：`python scripts/validate_note.py --note <path> --paper-type <type> --require-frontmatter --require-evidence --dataset-policy auto`
	- 回退仅用于无数据集型论文或确无公开数据集但有问题定义/评测协议/理论假设等替代证据的场景

7. Promotion
- 只有验证通过的 note 才能 promote 到正式目录。
- 推荐使用：
	- `python scripts/normalize_note_location.py --source <staging-note> --paper-notes-root <root> --domain <domain> --paper-folder <folder> --promote`
- 正式路径必须稳定且唯一，推荐：
	- `paper-notes/<domain>/<paper-folder>/<paper-folder>.md`
	- 或 `paper-notes/<domain>/<paper-folder>/note.md`

8. Blocked / Remediation
- 若 note 生成失败、metadata 不足、验证失败或路径异常，任务进入 blocked 状态。
- blocked 状态下允许补 metadata、重跑单篇、修复模板，但不允许以简版摘要冒充完成。
- 若连续两次生成失败，应显式汇报失败原因和缺失信息，不得继续静默重试。

## 论文级沉淀要求
- 每篇核心论文都必须形成独立分析。
- 每篇分析至少包含：研究动机、方法论、数据区间或数据集、核心结论、局限性。
- 不允许跳过论文级沉淀直接输出综述。

## 跨论文综合要求
- 综述、研究结论或路线建议必须建立在论文级笔记之上。
- 明确共识、分歧、趋势、空白点与潜在机会。
- 最终展示完整产出清单：论文笔记列表，以及综述卡片或综合结论列表。

## 知识卡沉淀工作流（一手抓取 → save_research）
沉淀「看卡不用查网」的深度知识卡（区别于论文笔记）时，走一手抓取工作流，让卡片自带出处、防链接失效：
1. `fetch_url` 抓关键 sources —— 返回正文 + 存本地快照（`knowledge/_snapshots/`，防招聘 JD / 网页下架后无法回溯）。
2. 基于抓到的正文写深度 answer（具体数字 / 机制，而非记忆）；`supporting_claims[].evidence_ids` 用 `sources` 里的 url，这样渲染成可点击来源链接。
3. `save_research` 存卡 —— 自动带 `source_years`/`info_freshness`/`version` 时效字段；`sources` 自动后台快照（即使没显式 fetch_url 也有备份）。
卡片落盘后跑质量门（frontmatter schema + 正文密度 + 时效），结果进 `card_quality` 字段（advisory）。超期卡用 `scholar-agent scan-stale`（`--refresh` 重抓 sources 快照）。

## 禁止事项
- 不要在搜索结果质量差时静默降级。
- 不要为了凑篇数保留低相关或低质量论文。
- 不要把综述卡片当作论文级笔记的替代品。
- 不要把未验证的 staging 文件写入正式 `paper-notes/`。
- 不要在缺少最低输入契约时调用完整 note 生成。

## 参考资料
- `references/workflow.md`
- `references/quality-gates.md`
- `references/path-policy.md`
