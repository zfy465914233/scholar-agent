# Scholar Agent 技术债治理与优化实施计划

> **版本**: v1.0
> **日期**: 2026-06-11
> **状态**: 待评审
> **范围**: 基于 2026-06-11 四维度深度审计（架构、性能、健壮性、工程质量）

---

## 0. 审计摘要

对 `py-scholar-agent` 项目进行了四个维度的深度审计，共发现 **47 项** 可优化项。本计划按工程优先级分为 6 个阶段（Phase 0–5），每个阶段独立可交付、可验证，且尽量不依赖后续阶段。

### 问题分布

| 严重级别 | 数量 | 典型问题 |
|---------|------|---------|
| P0 致命 | 4 | Docker 端口不匹配、非原子写入、SQLite 泄漏、线程不安全缓存 |
| P1 性能 | 6 | 重复全量扫描、串行 API 调用、BM25 全量排序、4 字节头全文件读 |
| P2 架构 | 6 | 巨型文件、三套 LLM 客户端、无数据模型、重复工具模式 |
| P3 健壮性 | 7 | 静默失败、错误吞没、双重重试机制、弱锁 |
| P4 质量 | 24+ | 类型安全缺口、依赖漂移、测试盲区、硬编码散布 |

---

## Phase 0: 紧急修复（1–2 天）

> 零架构改动，纯 bug 修复。每个改动独立、低风险、可单独验证。

### 0.1 Docker 端口对齐

**文件**: `Dockerfile:13`, `src/scholar_agent/server.py:1824`

**现状**: Dockerfile 暴露 `8000`，`server.py` 的 `start_local_server()` 硬编码 `port = 8374`。

**修改**:
```
# Dockerfile:13
EXPOSE 8374
```

同时，将 `server.py:1824` 的端口改为从环境变量读取：
```python
port = int(os.environ.get("SCHOLAR_PORT", "8374"))
```

**验证**: `docker build -t scholar-agent . && docker run -p 8374:8374 scholar-agent` 确认服务在 8374 端口响应。

---

### 0.2 paper_analyzer 非原子写入修复

**文件**: `src/scholar_agent/engine/academic/paper_analyzer.py:681`, `:1021`

**现状**: `generate_note` (line 681) 和 `fill_note_from_pdf` (line 1021) 使用裸 `open()` / `Path.write_text()`，进程中断会留下损坏文件。同模块已导入 `atomic_write_text` 但未使用。

**修改**:

line 681:
```python
# Before:
with open(note_path, "w", encoding="utf-8") as f:
    f.write(content)

# After:
atomic_write_text(Path(note_path), content)
```

line 1021:
```python
# Before:
Path(note_path).write_text(filled_content, encoding="utf-8")

# After:
atomic_write_text(Path(note_path), filled_content)
```

**验证**: 在 `generate_note` 写入期间 `kill -9` 进程，确认不存在部分写入文件（只有完整文件或不存在）。

---

### 0.3 distill_knowledge 非原子写入修复

**文件**: `src/scholar_agent/engine/distill_knowledge.py:95-96`

**现状**: 使用 `Path.write_text()`。

**修改**: 引入 `atomic_write_text`，同 0.2。

---

### 0.4 PaperStore 资源管理

**文件**: `src/scholar_agent/engine/paper_store.py`, 调用方

**现状**: `PaperStore.close()` (line 170) 存在但从未被调用。调用方 (`daily_workflow.py:45`, `cli.py:962`, `unified_pipeline.py:486`) 创建实例后依赖 GC。

**修改**: 所有 `PaperStore` 使用点改为上下文管理器模式。

首先，给 `PaperStore` 添加 `__enter__` / `__exit__`:
```python
# paper_store.py, 在 close() 之后添加
def __enter__(self) -> "PaperStore":
    return self

def __exit__(self, *exc: object) -> None:
    self.close()
```

然后，各调用点改为 `with PaperStore(...) as store:`。

涉及位置:
- `src/scholar_agent/engine/academic/daily_workflow.py:44-51`
- `src/scholar_agent/cli.py` (所有 `PaperStore(...)` 调用)
- `src/scholar_agent/engine/academic/unified_pipeline.py:486`

---

### 0.5 缓存线程安全

**文件**: `src/scholar_agent/engine/local_retrieve.py:25`, `src/scholar_agent/engine/scholar_config.py:23-24`

**现状**: `_bm25_cache` 和 `_config_cache` 是普通 `dict`，被 MCP `_run_blocking` 的多个线程并发访问。

**修改**: 使用 `threading.Lock` 保护。

```python
# local_retrieve.py
_bm25_lock = threading.Lock()
_bm25_cache: dict[tuple[str, float], tuple[BM25, list[dict]]] = {}

def _get_bm25(documents, index_path):
    cache_key = (str(index_path), index_path.stat().st_mtime)
    with _bm25_lock:
        if cache_key in _bm25_cache:
            return _bm25_cache[cache_key]
    bm25 = BM25(documents)
    with _bm25_lock:
        _bm25_cache[cache_key] = (bm25, documents)
        if len(_bm25_cache) > 4:
            oldest = next(iter(_bm25_cache))
            del _bm25_cache[oldest]
    return _bm25_cache[cache_key]
```

同样为 `scholar_config.py` 的 `_config_cache` 添加 `_config_lock`。

---

### 0.6 save_research 错误信息补全

**文件**: `src/scholar_agent/server.py:326-327`

**现状**: `return json.dumps({"error": f"Failed to write card: {type(e).__name__}"})` 只返回异常类型名。

**修改**: `return json.dumps({"error": f"Failed to write card: {e}"})`，与其他工具的错误格式保持一致。

---

### Phase 0 检查清单

- [ ] `docker build` + `docker run` 在 8374 端口正常工作
- [ ] `pytest tests/` 全部通过
- [ ] `grep -n "open(.*'w'" src/scholar_agent/engine/academic/paper_analyzer.py` 无结果
- [ ] `grep -n "PaperStore(" src/` 所有调用点均使用 `with` 语句
- [ ] `ruff check src/` 无新增告警
- [ ] `mypy src/` 无新增错误

---

## Phase 1: 性能热点修复（2–3 天）

> 针对审计中识别的最大性能瓶颈，每个改动可独立度量效果。

### 1.1 缓存 `get_analyzed_paper_ids`

**文件**: `src/scholar_agent/engine/academic/daily_workflow.py:30-74`

**现状**: 每次调用都打开新 SQLite 连接 + `rglob("*.md")` 全量扫描 + 全文件读取提取 `paper_id`。一次 Daily 推荐流程中被调用 **5 次**（lines 150, 192, 373, 440, 485）。

**修改**: 在 `generate_daily_recommendations()` 入口处调用一次，将结果作为参数传入各子函数。

```python
def generate_daily_recommendations(...):
    # 在流程最开始调用一次
    analyzed_ids = get_analyzed_paper_ids(paper_notes_dir)

    # 传递给各 track
    conf_results = _run_conference_track(..., analyzed_ids=analyzed_ids)
    innov_results = _run_innovation_track(..., analyzed_ids=analyzed_ids)
    ...
```

同时，`get_analyzed_paper_ids` 内部改为只在 SQLite 可用时走数据库查询（已分析论文 ID 已持久化在 `papers` 表中），SQLite 不可用时才走文件扫描。

**预期收益**: 消除 4 次冗余的全文件系统扫描，Daily 推荐速度提升约 30–60 秒（取决于笔记数量）。

---

### 1.2 缓存 `_probe_local_score` 的 BM25 构建

**文件**: `src/scholar_agent/engine/orchestrate_research.py:118-133`

**现状**: 每次 `classify_route()` 都全量读取 JSON → 解析 → 构建 BM25 索引 → 查询 → 丢弃。

**修改**: 复用 `local_retrieve.py` 中已有的 `_bm25_cache` 机制（Phase 0.5 已加锁）。将 BM25 实例化提取到可缓存的位置。

```python
def _probe_local_score(query, knowledge_dir, ...):
    idx_path = index_path or (Path(knowledge_dir) / "index.json")
    # 复用已有的缓存机制
    raw = Path(idx_path).read_text(encoding="utf-8")
    index_data = json.loads(raw)
    documents = [...]  # 从 index_data 构建
    bm25, _ = _get_bm25(documents, idx_path)  # 复用缓存
    results = bm25.top_k(query, k=3)
    ...
```

**预期收益**: 每次 `classify_route` 节省数百毫秒的 JSON 解析 + BM25 索引构建时间。

---

### 1.3 `is_card()` 只读前 4 字节

**文件**: `src/scholar_agent/engine/local_index.py:102-105`

**现状**: `path.read_text()` 读取整个文件只为检查 `startswith("---\n")`。

**修改**:
```python
def is_card(path: Path) -> bool:
    if "templates" in path.parts or path.name.lower() == "readme.md" or not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            header = f.read(4)
        return header in ("---\n", "---\r\n")
    except (OSError, UnicodeDecodeError):
        return False
```

**预期收益**: 对于 N 张知识卡片，将 `O(N × avg_card_size)` 的 I/O 降至 `O(N × 4 bytes)`。在大知识库（1000+ 卡片）上，索引构建可节省数秒。

---

### 1.4 BM25 `top_k` 使用堆选取

**文件**: `src/scholar_agent/engine/bm25.py:185-186`

**现状**: `top_k` 调用 `score()` 对全部文档排序后取前 k，复杂度 O(n log n)。

**修改**: 使用 `heapq.nlargest`:
```python
import heapq

def top_k(self, query: str, k: int = 5) -> list[tuple[int, float, list[str]]]:
    scored = self.score_unsorted(query)  # 新方法，不排序
    return heapq.nlargest(k, scored, key=lambda x: x[1])
```

需要将 `score()` 拆分为不排序的内部方法和排序的外部方法，保持 `score()` 的向后兼容。

**预期收益**: 当知识库文档数 n >> k 时，从 O(n log n) 降至 O(n log k)。对 10000 文档取 top 5，快约 10 倍。

---

### 1.5 S2 批量查询并行化

**文件**: `src/scholar_agent/engine/academic/conf_search.py:269-301`

**现状**: `_batch_search_s2()` 逐标题串行请求 S2 API，每次间隔 100ms。

**修改**: 使用 `ThreadPoolExecutor` 并行化，同时控制并发不超过 3（避免触发限流）:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _batch_search_s2(titles, ...):
    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_search_single_s2, title, ...): title for title in titles}
        for future in as_completed(futures):
            title = futures[future]
            try:
                results[title] = future.result()
            except Exception:
                logger.warning("S2 lookup failed for: %s", title[:50])
    return results
```

**预期收益**: 10 个标题从 ~2s（10 × 200ms）降至 ~0.8s（4 轮 × 200ms）。

---

### 1.6 Quality Funnel Stage 3 LLM 并行化

**文件**: `src/scholar_agent/engine/academic/quality_funnel.py:272-353`

**现状**: 逐论文串行 LLM 调用 + 1s sleep。

**修改**: 使用 `ThreadPoolExecutor` 批量调用，每批 5 个并行:

```python
def _review_batch(papers, prompt_fn, delay):
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_review_single, p, prompt_fn): p for p in papers}
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception:
                pass
            if delay > 0:
                time.sleep(delay)
    return results
```

**预期收益**: 50 篇论文从 ~75s 降至 ~20s。

---

### 1.7 Daily 推荐双轨并行

**文件**: `src/scholar_agent/engine/academic/daily_workflow.py:264-293`

**现状**: `generate_daily_recommendations()` 中 conference track 和 arXiv innovation track 串行执行。

**修改**: 使用 `ThreadPoolExecutor` 并行:
```python
with ThreadPoolExecutor(max_workers=2) as pool:
    conf_future = pool.submit(_run_conference_track, ...)
    innov_future = pool.submit(_run_innovation_track, ...)
    conf_results = conf_future.result()
    innov_results = innov_future.result()
```

**预期收益**: Daily 推荐总耗时减少约 40%（取决于两个 track 中较慢的那个）。

---

### 1.8 `upsert_papers` 批量事务

**文件**: `src/scholar_agent/engine/paper_store.py:293-299`

**现状**: 循环调用 `upsert_paper()`，每次都是一个独立事务（commit）。

**修改**: 在一个事务内执行所有 INSERT:
```python
def upsert_papers(self, papers: list[dict[str, Any]]) -> int:
    cur = self._conn.cursor()
    try:
        count = 0
        for raw in papers:
            paper = _normalize_paper(raw)
            cur.execute("INSERT OR IGNORE ...", (...))
            count += cur.rowcount
        self._conn.commit()
    except Exception:
        self._conn.rollback()
        raise
    finally:
        cur.close()
    return count
```

**预期收益**: 200 篇论文的批量插入从 200 次事务降至 1 次，约快 10–50 倍。

---

### Phase 1 检查清单

- [ ] `pytest tests/` 全部通过
- [ ] Daily 推荐端到端测试可运行（`scholar-agent daily`）
- [ ] 性能基准：记录 Daily 推荐执行时间，与优化前对比
- [ ] `grep -n "time.sleep" src/scholar_agent/engine/academic/` 确认不必要的 sleep 已消除
- [ ] SQLite WAL 模式下并发写入无死锁

---

## Phase 2: server.py 拆分（2–3 天）

> 不改变任何业务逻辑，纯结构重组。

### 2.1 拆分方案

当前 `server.py`（1851 行）拆为 4 个文件:

```
src/scholar_agent/
  server.py              # 入口 + MCP 实例创建 (~100 行)
  tools/
    __init__.py
    knowledge_tools.py   # query_knowledge, save_research, list_knowledge,
                         # capture_answer, ingest_source, build_graph    (~430 行)
    academic_tools.py    # search_papers, search_conf_papers, analyze_paper,
                         # download_paper, extract_paper_images, paper_to_card,
                         # daily_recommend, link_paper_keywords,
                         # import_paperpulse_note                          (~930 行)
    _helpers.py          # _run_blocking, _tool_timeout, _validate_path_within,
                         # _configured_index_path, _parse_arxiv_id, _find_local_pdf
  http_server.py         # ScholarAgentLocalServer + start_local_server   (~200 行)
```

### 2.2 导入兼容性

`server.py` 作为入口保持对外的 API 兼容：
```python
# server.py — 精简入口
from scholar_agent.tools.knowledge_tools import *  # 注册到 mcp
from scholar_agent.tools.academic_tools import *   # 注册到 mcp (if SCHOLAR_ACADEMIC)
from scholar_agent.http_server import start_local_server

mcp = FastMCP("scholar-agent", ...)

def main():
    ...
    mcp.run()
```

MCP 工具通过装饰器注册，只要在 `mcp.run()` 之前导入即可，因此拆分不影响运行时行为。

### 2.3 HTTP 服务独立

`http_server.py` 导出 `ScholarAgentLocalServer` 和 `start_local_server`，不再与 MCP 工具定义耦合。

---

### Phase 2 检查清单

- [ ] `scholar-agent serve-mcp` 正常启动，所有 15 个工具可用
- [ ] `scholar-agent serve-mcp --http` HTTP 同步端点正常
- [ ] `pytest tests/` 全部通过
- [ ] 新文件均无 `Any` 类型告警（`mypy` 通过）
- [ ] `wc -l` 确认无文件超过 500 行

---

## Phase 3: 统一 LLM 客户端（3–4 天）

> 消除三套独立 LLM 调用实现，引入统一抽象。

### 3.1 当前状态

| 位置 | 实现方式 | 凭证来源 |
|------|---------|---------|
| `paper_analyzer.py:845-945` | urllib + Anthropic/OpenAI 兼容格式 | 15+ 个环境变量 |
| `domain_router.py:414-452` | raw urllib，自定义 prompt 格式 | `ROUTER_LLM_*` 环境变量 |
| `synthesize_answer.py:114-151` | 又一套 urllib | 独立环境变量读取 |

### 3.2 目标架构

```
src/scholar_agent/engine/
  llm_client.py          # 统一 LLM 客户端 (~150 行)
```

```python
# llm_client.py
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class LLMConfig:
    api_url: str
    api_key: str
    model: str
    max_tokens: int = 4096
    timeout: int = 60

class LLMClient(Protocol):
    def complete(self, system_prompt: str, user_message: str) -> str: ...

class OpenAICompatClient:
    """兼容 OpenAI 和 Anthropic API 格式的统一客户端"""

    def __init__(self, config: LLMConfig):
        self._config = config

    def complete(self, system_prompt: str, user_message: str) -> str:
        # 使用 urllib（无新依赖），统一错误处理和重试
        ...

def resolve_llm_config(purpose: str = "default") -> LLMConfig:
    """从环境变量和配置文件解析 LLM 配置，带缓存"""
    ...
```

### 3.3 迁移路径

1. 实现 `llm_client.py`，保持 urllib（不引入新依赖）
2. `paper_analyzer.py` — `_resolve_providers` → `resolve_llm_config("analyzer")`，`_call_llm_*` → `client.complete()`
3. `domain_router.py` — `_call_router_llm` → `client.complete()`
4. `synthesize_answer.py` — LLM 调用 → `client.complete()`
5. `quality_funnel.py` — Stage 3 LLM 调用 → `client.complete()`

### 3.4 凭证解析统一

当前 `_resolve_providers` (paper_analyzer.py:764-842) 检查约 15 个环境变量，有优先级逻辑。统一为:

```python
def resolve_llm_config(purpose: str = "default") -> LLMConfig:
    """解析优先级:
    1. {PURPOSE}_LLM_API_KEY / {PURPOSE}_LLM_API_URL / {PURPOSE}_LLM_MODEL
    2. LLM_API_KEY / LLM_API_URL / LLM_MODEL  (通用)
    3. ANTHROPIC_API_KEY / OPENAI_API_KEY       (向后兼容)
    """
```

结果缓存到模块级变量，避免重复解析。

### 3.5 统一重试

当前有两套重试机制:
- `retry.py:retry_with_backoff` — 通用，支持 jitter/回调
- `arxiv_search.py:_with_retry` — 简化版，静默返回 None

迁移后，`_with_retry` 改为调用 `retry_with_backoff`，LLM 调用统一使用 `retry_with_backoff` 并配置合理的异常类型过滤。

---

### Phase 3 检查清单

- [ ] `paper_analyzer.generate_note` 生成的笔记与之前质量一致
- [ ] `domain_router` 路由结果与之前一致
- [ ] `synthesize_answer` 综合结果与之前一致
- [ ] `grep -rn "urlopen" src/scholar_agent/engine/` 仅出现在 `llm_client.py` 和 API 调用中
- [ ] LLM 凭证错误时返回清晰的错误信息（而非静默失败）
- [ ] 所有 LLM 调用有统一的超时和重试行为

---

## Phase 4: 数据模型与类型安全（3–4 天）

### 4.1 Paper 数据模型

**现状**: 论文记录以 `dict[str, Any]` 在 `arxiv_search` → `scoring` → `quality_funnel` → `daily_workflow` → `paper_analyzer` → `server.py` 全链路传递。

**目标**: 引入 `PaperRecord` dataclass。

```python
# src/scholar_agent/engine/models.py
from dataclasses import dataclass, field

@dataclass
class PaperRecord:
    title: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    arxiv_id: str = ""
    score: float = 0.0
    url: str = ""
    pdf_url: str = ""
    published: str = ""
    # ... 其他字段

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PaperRecord":
        """从现有 dict 构造，忽略未知字段"""
        ...

    def to_dict(self) -> dict[str, Any]:
        """序列化为 MCP 兼容的 dict"""
        ...
```

**迁移策略**: 分步进行，不一次性替换所有 `dict`:
1. `models.py` 定义 `PaperRecord`
2. `arxiv_search.py` — 搜索结果返回 `list[PaperRecord]`
3. `scoring.py` — 接收 `PaperRecord`，在其上设置 `score`
4. `daily_workflow.py` / `paper_analyzer.py` — 接收 `PaperRecord`
5. `server.py` — 在 MCP 响应序列化时调用 `.to_dict()`

每一步保持 `from_dict` / `to_dict` 兼容，确保未迁移的模块仍能以 dict 形式交互。

### 4.2 `build_knowledge_card` 拆分

**文件**: `src/scholar_agent/engine/close_knowledge_loop.py:418-739`

**现状**: 单个 320 行函数承担路由、标签推断、frontmatter 生成、目录构建、正文组装、实体提取、矛盾检查、文件写入。

**拆分方案**:

```python
def build_knowledge_card(query, answer_data, research_data, knowledge_root, ...) -> Path:
    """编排器 — 调用以下子步骤"""
    card_type = _infer_card_type(answer_data)
    tags = _infer_tags(query, answer_data, card_type)
    frontmatter = _build_frontmatter(query, tags, card_type, ...)
    sections = _build_sections(answer_data, research_data)
    visual_aids = _extract_visual_aids(answer_data)
    body = _assemble_body(frontmatter, sections, visual_aids)
    card_path = _write_card(knowledge_root, domain, card_id, body)
    append_changelog(card_path, query)
    return card_path

def _infer_tags(...) -> list[str]: ...
def _build_frontmatter(...) -> str: ...
def _build_sections(...) -> list[str]: ...
def _extract_visual_aids(...) -> list[dict]: ...
def _assemble_body(...) -> str: ...
def _write_card(...) -> Path: ...
```

每个子函数可独立测试。

### 4.3 消除 `_generate_zh_note` / `_generate_en_note` 重复

**文件**: `src/scholar_agent/engine/academic/paper_analyzer.py:164-560`

**现状**: 两个各约 200 行的函数，逻辑完全相同，仅字符串语言不同。

**修改**: 合并为一个参数化函数:

```python
def _generate_note(
    paper: PaperRecord,
    *,
    language: Literal["zh", "en"],
    sections: list[str],
    images: list[dict] | None = None,
    math_depth: str = "moderate",
) -> str:
    """根据语言参数生成本地化笔记"""
    # 使用 _STRINGS[language] 字典查找所有本地化字符串
    ...
```

将两套字符串提取为:
```python
_STRINGS = {
    "zh": {
        "core_info": "核心信息",
        "abstract": "摘要翻译",
        "background": "研究背景",
        ...
    },
    "en": {
        "core_info": "Core Information",
        "abstract": "Abstract",
        "background": "Background",
        ...
    },
}
```

---

### Phase 4 检查清单

- [ ] `PaperRecord` 的 `from_dict` / `to_dict` 往返无损
- [ ] `scholar-agent search` 返回结果与重构前一致
- [ ] `scholar-agent analyze` 生成的中英文笔记格式正确
- [ ] `build_knowledge_card` 的子函数均有独立测试
- [ ] `mypy src/` 无新增错误

---

## Phase 5: 工程质量收尾（2–3 天）

### 5.1 Dockerfile 改进

**文件**: `Dockerfile`

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/scholar-agent /usr/local/bin/scholar-agent
ENV SCHOLAR_HOME=/data
RUN mkdir -p /data
EXPOSE 8374
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8374/health')"
ENTRYPOINT ["scholar-agent"]
CMD ["serve-mcp"]
```

添加 `.dockerignore`:
```
.git
.venv
__pycache__
*.pyc
tests
docs
*.md
!README.md
```

### 5.2 Makefile 统一为 uv

**文件**: `Makefile`

将所有 `pip install` 替换为 `uv pip install` 或 `uv sync`，与 `uv.lock` 保持一致。

### 5.3 删除 `requirements.txt`

与 `pyproject.toml` 重复且不同步，直接删除。如有 CI 需要固定版本，`uv.lock` 已提供。

### 5.4 收窄依赖版本范围

**文件**: `pyproject.toml`

```toml
dependencies = [
    "jsonschema>=4.23,<5",
    "fastmcp>=2.0,<3",       # 收窄到下一个大版本
    "PyMuPDF>=1.24.0,<2",    # 加上界
    "requests>=2.28,<3",     # 加上界
]
```

### 5.5 提升覆盖率门槛

渐进提升:
- 当前: `fail_under = 60`
- 本阶段: `fail_under = 70`（补充 Phase 0–4 新代码的测试）
- 目标: `fail_under = 80`（后续迭代）

重点补充测试:
- `import_service.py` — 完全无测试
- `paper_analyzer.py` — 完全无测试（至少覆盖 `generate_note` 的参数构建和错误路径）
- API 失败场景（mock HTTP 响应）
- 并发访问场景（验证 Phase 0.5 的锁）

### 5.6 收紧 mypy 配置

```toml
[tool.mypy]
disallow_untyped_defs = true  # 从 false 改为 true
```

对于暂时无法标注的模块，使用 override:
```toml
[[tool.mypy.overrides]]
module = ["scholar_agent.cli", "scholar_agent.runtime"]
disallow_untyped_defs = false  # 逐步收紧
```

### 5.7 硬编码提取

将以下硬编码提取到 `config/constants.py` 或配置文件:

| 当前位置 | 硬编码 | 提取为 |
|---------|--------|--------|
| `server.py:1824` | `8374` | `DEFAULT_PORT` |
| `server.py:92-97` | 超时字典 | `TOOL_TIMEOUTS` |
| `domain_router.py:411` | `"gpt-4o-mini"` | `DEFAULT_LLM_MODEL` |
| `common.py:152` | `120` (截断长度) | `TITLE_MAX_LENGTH` |
| `close_knowledge_loop.py:314-317` | 质量评分权重 | `QUALITY_WEIGHTS` |

---

### Phase 5 检查清单

- [ ] `docker build` 镜像大小比之前减少（多阶段构建）
- [ ] `make lint` / `make test` 全部通过
- [ ] `coverage report` 显示 ≥ 70%
- [ ] 无 `requirements.txt` 文件
- [ ] `grep -rn "port = 8374" src/` 无硬编码结果
- [ ] `grep -rn "gpt-4o-mini" src/` 无硬编码结果

---

## 风险评估

| 阶段 | 主要风险 | 缓解措施 |
|------|---------|---------|
| Phase 0 | PaperStore `with` 语句可能遗漏调用点 | `grep -rn "PaperStore(" src/` 确认所有调用点 |
| Phase 1 | 并行化引入线程安全问题 | 所有共享状态检查是否已加锁（Phase 0.5 已覆盖） |
| Phase 2 | 工具注册依赖导入时序 | MCP 装饰器注册是全局的，只要在 `mcp.run()` 前导入即可 |
| Phase 3 | LLM 调用格式变更导致输出质量变化 | 每个 client 迁移后做 A/B 对比测试 |
| Phase 4 | PaperRecord 迁移可能遗漏 dict 访问点 | `from_dict`/`to_dict` 保证过渡期兼容 |
| Phase 5 | mypy 收紧可能产生大量告警 | 先排除已有告警文件，逐步收紧 |

---

## 时间线总览

```
Week 1:  Phase 0 (紧急修复) + Phase 1 启动
Week 2:  Phase 1 完成 + Phase 2 (server.py 拆分)
Week 3:  Phase 3 (统一 LLM 客户端) + Phase 4 启动
Week 4:  Phase 4 完成 + Phase 5 (质量收尾)
```

总计约 **13–16 个工作日**。

---

## 附录 A: 不在本计划范围内的事项

以下审计发现记录但不在本次治理范围:

1. **全面 async 改造** — 当前 engine 层全是同步代码，全面改为 async 影响面过大。`_run_blocking` 的线程池封装在当前规模下足够。建议作为 v2 的专项。
2. **前端 UI / PaperPulse 集成** — 不在本仓库范围。
3. **embedding 检索优化** — `sentence-transformers` 是可选依赖，优化优先级低。
4. **自定义 YAML 解析器替换** — 引入 `pyyaml` 作为必需依赖可解决，但影响所有解析路径，需更大范围的回归测试。
