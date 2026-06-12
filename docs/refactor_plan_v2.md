# Scholar Agent 重构计划 v2

> **版本**: v2.0（综合评估反馈修正）
> **日期**: 2026-06-11
> **原则**: 第一性原理 — 只做对用户价值有贡献的改动

---

## 核心价值链

```
学术论文/知识输入 → 结构化处理(LLM) → 本地知识库 → BM25/语义检索 → IDE 内回答
```

**判断标准**: 是否让用户更快、更可靠地获取高质量知识回答？

---

## Phase 0: 真正的 Bug（~2 小时）

> 零架构改动，每个修复独立可验证。

### 0.1 Docker 端口对齐

**文件**: `Dockerfile:13`, `server.py:1824`

Dockerfile 暴露 8000，代码硬编码 8374。

修改: Dockerfile 改为 `EXPOSE 8374`；`server.py:1824` 改为读取环境变量 `SCHOLAR_PORT`（默认 8374）。

### 0.2 paper_analyzer 非原子写入

**文件**: `paper_analyzer.py:681,1021`

使用裸 `open()` / `write_text()`，进程中断会损坏文件。`atomic_write_text` 在 `common.py` 中已存在。

修改: 添加 `from scholar_agent.engine.common import atomic_write_text`，替换两处写入。

### 0.3 distill_knowledge 非原子写入 + origin 不匹配

**文件**: `distill_knowledge.py:96,53`

两个问题: (1) 使用 `write_text()` 非原子写入；(2) `origin: generated_from_answer_context` 不在 `ORIGINS` 集合中（`knowledge_lifecycle.py:53`），会导致验证警告。

修改: 原子写入 + 将 origin 改为 `"distilled"`（已在 ORIGINS 中）。

### 0.4 PaperStore 上下文管理器

**文件**: `paper_store.py`, 所有调用点

`close()` 方法存在但从未被调用。

修改: 添加 `__enter__`/`__exit__`，所有调用点改为 `with PaperStore(...) as store:`。

### 0.5 save_research 错误信息

**文件**: `server.py:326-327`

只返回异常类型名 `PermissionError`，丢失文件路径等关键信息。

修改: 返回 `str(e)`。

### 0.6 is_card() 只读前 4 字节

**文件**: `local_index.py:102-105`

`path.read_text()` 读取整个文件只为 `startswith("---\n")`。

修改: 改为 `f.read(4)`。

### 0.7 缓存线程安全

**文件**: `local_retrieve.py:25`, `scholar_config.py:23-24`

`_bm25_cache` 和 `_config_cache` 是裸 dict，被 `_run_blocking` 的线程池并发访问。

修改: 添加 `threading.Lock` 保护。

---

## Phase 1: 高 ROI 性能优化（1–2 天）

### 1.1 缓存 get_analyzed_paper_ids

**文件**: `daily_workflow.py:30-74`

每次调用都打开新 SQLite + rglob 全量扫描。一次 Daily 流程调用 5 次。

修改: 入口处调用一次，结果作为参数传入。

### 1.2 缓存 BM25 构建

**文件**: `orchestrate_research.py:118-133`

每次分类都重建 BM25 索引。

修改: 复用 `local_retrieve.py` 已有的 `_bm25_cache`。

### 1.3 Daily 推荐双轨并行

**文件**: `daily_workflow.py:264-293`

conference track 和 innovation track 串行执行。

修改: `ThreadPoolExecutor` 并行。**注意**: 每个线程需独立的 PaperStore 连接（SQLite 不跨线程共享）。

---

## Phase 2: 统一 LLM 客户端（3–4 天）

> Plan 中最有价值的结构性改进。

### 2.1 问题

5 处独立的 `urlopen` LLM 调用，各自处理凭证、格式、错误。

### 2.2 方案

`src/scholar_agent/engine/llm_client.py`:
- 统一凭证解析（带缓存），消除 6+ 文件中的 `os.environ.get()` 散布
- 处理 Anthropic vs OpenAI 消息格式差异（Anthropic 用独立 `system` 字段，OpenAI 用 `messages[0].role="system"`）
- 统一重试（复用 `retry.py` 的 `retry_with_backoff`）
- 统一超时和错误处理
- 添加请求/响应日志（可观测性基础）

### 2.3 迁移顺序

paper_analyzer → domain_router → synthesize_answer → research_harness

---

## Phase 3: 结构优化（按需，2–3 天）

### 3.1 zh/en 笔记合并

`paper_analyzer.py:164-560` 两个 ~200 行函数合并为参数化函数。

### 3.2 build_knowledge_card 拆分

`close_knowledge_loop.py:418-739` 的 320 行函数拆分为可测试的子函数。

### 3.3 server.py 拆分

如果团队觉得有必要。纯可读性改善，不改变运行时行为。

---

## 不做的事

| 项目 | 原因 |
|------|------|
| PaperRecord dataclass 迁移 | 过度工程化，dict 在当前场景够用 |
| BM25 heapq 优化 | 知识库 <10000 文档时差异微秒级 |
| S2 批量并行 | 低频操作，引入线程复杂度不值得 |
| Quality Funnel LLM 并行 | 可能触发 API 限流 |
| upsert_papers 批量事务 | SQLite WAL 下性能已够 |
| mypy strict mode | 当前会产生数百错误，ROI 极低 |
| 删除 requirements.txt | 可能破坏现有工作流 |
| Makefile uv 统一 | 纯偏好，不影响用户 |
