# Phase 6: 演进路线 — 语义检索 + 工程韧性 + 路由升级

Date: 2026-04-02

## 目标

将 optimizer 从"能跑的脚手架"推进到"日常可用的知识系统"，重点解决三个瓶颈：
语义检索弱、外部 API 脆弱、路由僵硬。

---

## Phase 6a: 本地语义检索升级

**问题**: BM25 只能匹配关键词，无法理解语义。查询"降水反演方法"搜不到标题含"QPE"的卡片。
**方案**: 引入 sentence-transformers 本地 embedding 模型，重写 `embedding_retrieve.py`。

具体改动：
1. `embedding_retrieve.py` — 用 `sentence-transformers` 替换空壳 API 调用，支持本地模型
2. `local_index.py` — 新增 `--build-embedding-index` 选项，为所有知识卡构建 embedding 索引
3. `local_retrieve.py` — hybrid 模式默认生效（BM25 + embedding 加权融合）
4. 零依赖兼容 — sentence-transformers 为可选依赖，不可用时自动降级为纯 BM25

模型选择: `all-MiniLM-L6-v2`（轻量 80MB，中英文兼顾，无需 GPU）

---

## Phase 6b: 外部 API 工程韧性

**问题**: SearXNG、Semantic Scholar、OpenAlex 的 `try/except pass` 无重试，网络波动直接丢数据。
**方案**: 在 `research_harness.py` 中引入统一的重试 + 退避工具函数。

具体改动：
1. 新增 `scripts/retry.py` — 通用 `retry_with_backoff()` 函数，指数退避 + 最大重试次数 + 可选 jitter
2. `research_harness.py` — 对 `search_searxng()`、`fetch_openalex()`、`fetch_semantic_scholar()` 包裹重试
3. 重试失败时将错误信息写入 evidence 的 `retrieval_status: "failed_after_retries"`

---

## Phase 6c: 路由器增强

**问题**: Router 用 `if "latest" in query` 这种硬规则，无法理解"最近进展"等近义词。
**方案**: 不上 LLM Router（过度工程），而是用关键词扩展 + 本地检索命中率做智能决策。

具体改动：
1. `agent.py` Router — 增加 query 扩展表（synonym map），如 "最新/最近/进展/current/latest" 统一映射
2. 新增"试探检索"逻辑 — 先用 local 检索，如果 top-1 分数低于阈值（如 2.0），自动切换为 web-led
3. 保留规则 fallback — 扩展表和试探检索都不覆盖时，仍走原有规则

---

## 验收标准

- [ ] embedding 不可用时自动降级为 BM25，所有测试通过
- [ ] embedding 可用时，语义查询（如"降水估计方法"）能检索到 QPE 卡片
- [ ] SearXNG 断连后重试 3 次再报错，重试间隔递增
- [ ] Router 对"最新进展"类查询正确路由为 web-led
- [ ] 全部 78+ 现有测试不回归
