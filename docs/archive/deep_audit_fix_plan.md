# Scholar-Agent 深度审计修复计划

> 生成日期：2026-06-11
> 依据：`docs/deep_audit_report.md` 复核结果
> 目标：优先修复已被源码证实的安全、资源泄漏、数据一致性和可靠性问题；对误判项不做无意义重构。

---

## 0. 复核结论

原审计报告包含多条真实问题，但严重度排序和部分判断不完全准确。

确认需要修复：

- HTTP `/import-markdown` 在未配置 token 时信任缺失 `Origin` 与可伪造 `Host`，应改为基于实际 peer IP 判断本机请求。
- PyMuPDF 文档对象未使用上下文管理器，异常路径可能泄漏文件句柄和 mmap 资源。
- 知识卡片生成字段与生命周期校验枚举不一致，导致自动生成卡片验证失败或产生不必要警告。
- dual-track daily workflow 缺少 track 级异常隔离，一个 track 失败会丢掉另一个 track 的结果。
- `Content-Length` 解析缺少异常处理，畸形请求会触发未捕获异常。
- `import_paperpulse_note` 与 HTTP import 成功后可能用 `Path("")` 触发错误 reindex 目标。
- BM25 结果组装直接索引字段，遇到旧索引或不完整文档可能 `KeyError`。
- urllib fallback response 未显式关闭。
- 关键 JSON/Markdown 文件写入缺少原子替换，崩溃时可能留下截断文件。

不按原报告修复或降级处理：

- C3 “同步 MCP 工具阻塞事件循环”证据不足。FastMCP 3.x 已将同步工具放入 threadpool 执行。后续可另立任务把长任务改成 task/background job，但不作为本轮 Critical 修复。
- M9 “`transition_card()` 从未调用”是误判，实际在 `knowledge_governance.py` 中调用。
- L5 arXiv tar 文件未清理是非问题，外层 `TemporaryDirectory` 会清理。

---

## 1. 第一批：安全与硬错误

### 1.1 修复 HTTP import 本机认证判断

文件：

- `src/scholar_agent/server.py`

计划：

- 在 `ScholarImportHandler.do_POST()` 中，未配置 `paperpulse_token` 时不再信任 `Origin is None`。
- 使用 `self.client_address[0]` 判断实际 peer IP 是否为 `127.0.0.1` 或 `::1`。
- `Host` 检查保留为辅助约束，但不能替代 peer IP。
- 对 IPv6 localhost 和 IPv4-mapped localhost 做兼容处理。

验证：

- 添加或更新 HTTP import 单元测试：
  - 未配置 token + peer IP localhost + localhost Host：允许。
  - 未配置 token + 非 localhost peer：拒绝。
  - 配置 token 后：只按 token 严格匹配。

### 1.2 修复 Content-Length 解析

文件：

- `src/scholar_agent/server.py`

计划：

- 将 `int(self.headers.get("Content-Length", 0))` 包入 `try/except`。
- 非数字、负数、缺失值分别返回合理错误：
  - 非数字：`400 Invalid Content-Length`
  - 负数：`400 Invalid Content-Length`
  - 超过 10 MB：保持 `413`

验证：

- 添加畸形 `Content-Length` 的 handler 单元测试。

### 1.3 修复导入后的 reindex 路径

文件：

- `src/scholar_agent/server.py`

计划：

- `import_paperpulse_note()` 和 HTTP `/import-markdown` 成功后不使用 `Path(config.get("index_path", ""))`。
- 改用 `get_index_path()` 作为默认入口；仅在显式配置非空 `index_path` 时使用配置值。
- 避免 `Path("")` 指向当前工作目录。

验证：

- 更新 `tests/test_import_paperpulse.py` 或相关 server 测试，覆盖空配置时 reindex 使用默认 index path。

---

## 2. 第一批：资源释放

### 2.1 修复 PyMuPDF 文档句柄泄漏

文件：

- `src/scholar_agent/engine/academic/image_extractor.py`

计划：

- `extract_pdf_text()` 改为 `with fitz.open(pdf_path) as doc:`。
- `_pull_embedded_images()` 改为 `with fitz.open(pdf_path) as doc:`。
- 保留内部 `doc.extract_image()` 的 per-image 容错。

验证：

- 现有测试若没有覆盖，可添加轻量 monkeypatch 测试：模拟 page/text 或 extract 异常时 `close()` 仍被调用。

### 2.2 修复 urllib fallback response 未关闭

文件：

- `src/scholar_agent/engine/academic/image_extractor.py`

计划：

- `_fetch_bytes()` 的 urllib fallback 改为 `with _url_lib.urlopen(...) as resp:`。

验证：

- monkeypatch `urlopen` 返回带 `__enter__/__exit__` 的 fake response，确认读取路径正常。

---

## 3. 第一批：知识卡片 schema 一致性

### 3.1 修复 `confidence` 与 `origin` 枚举不匹配

文件：

- `src/scholar_agent/engine/knowledge_lifecycle.py`
- 可能涉及：`tests/test_knowledge_lifecycle*.py`

计划：

- 将 `"draft"` 加入 `CONFIDENCE_LEVELS`，因为生成器明确产出 `confidence: draft`，且语义上表示尚未确认。
- 将 `"web_research_with_synthesis"` 加入 `ORIGINS`，因为 `build_knowledge_card()` 目前固定写入该来源。
- 保持 `review_status: draft` 与 `LifecycleState.DRAFT` 不变。

验证：

- 添加或更新测试：`build_knowledge_card()` 生成的 metadata 通过 `validate_card()` 不应包含 `confidence` error 或 `origin` warning。

---

## 4. 第二批：daily workflow 可靠性

### 4.1 dual-track 异常隔离

文件：

- `src/scholar_agent/engine/academic/daily_workflow.py`

计划：

- 为 conference track 和 arXiv innovation track 分别加 `try/except`。
- 单个 track 失败时返回该 track 的空结果和错误信息，不影响另一个 track。
- 返回结构增加 `track_errors` 或在 `tracks.{name}.error` 中记录错误，保证调用方可见。
- 总 `papers/skipped/total_found` 从成功 track 汇总。

验证：

- 单元测试：
  - conference 成功、arXiv 抛错：返回 conference 论文，`dual_track=True`，包含 arXiv 错误。
  - conference 抛错、arXiv 成功：返回 arXiv 论文，包含 conference 错误。
  - 两者都失败：返回空论文和两个错误。

### 4.2 note generation 失败可见性

文件：

- `src/scholar_agent/engine/academic/daily_workflow.py`

计划：

- `generate_paper_notes_for_daily()` 目前只返回 `stems`，失败只写日志。
- 为避免破坏现有调用，先保守扩展：
  - 记录失败到 logger 继续保留。
  - 若上层已有 daily note content 构造可接收失败信息，则增加可选返回结构；否则另立后续任务。

验证：

- 本轮不强行改变公开返回类型，避免扩大影响面。

---

## 5. 第二批：检索稳定性与性能

### 5.1 BM25 结果字段容错

文件：

- `src/scholar_agent/engine/local_retrieve.py`

计划：

- `retrieve_bm25()` 组装结果时改用 `.get()`，与 `retrieve_hybrid()` 保持一致。
- 对关键字段设置合理默认值：
  - `doc_id`: `doc.get("doc_id", "")`
  - `path`: `doc.get("path", "")`
  - `title`: `doc.get("title", "")`
  - `type`: `doc.get("type", "")`
  - `topic`: `doc.get("topic", "")`

验证：

- 添加测试：缺少 `topic` 或 `type` 的文档不会抛 `KeyError`。

### 5.2 embedding index 加载缓存

文件：

- `src/scholar_agent/engine/local_retrieve.py`

计划：

- 本轮先不做复杂缓存，避免缓存失效策略引入新问题。
- 若要修，使用路径 + mtime + size 作为 cache key，缓存 JSON 解析结果。

验证：

- 若实施缓存，添加 mtime 变化后重新加载的测试。

---

## 6. 第三批：原子写入

### 6.1 引入统一原子写入 helper

文件：

- `src/scholar_agent/engine/common.py`

计划：

- 新增 `atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None`。
- 实现方式：
  - 在目标文件同目录创建临时文件。
  - 写入并 flush/fsync。
  - `Path.replace()` 原子替换目标。
  - 异常时清理临时文件。

优先替换位置：

- `src/scholar_agent/engine/local_index.py` 的 index 和 embedding index 写入。
- `src/scholar_agent/engine/close_knowledge_loop.py` 的知识卡片写入。
- `src/scholar_agent/engine/import_service.py` 的导入文件写入。
- `src/scholar_agent/engine/academic/daily_workflow.py` 的 daily note 写入。

验证：

- helper 单元测试：正常写入、覆盖写入、异常清理。
- 运行相关现有测试：local index、import、daily workflow、knowledge lifecycle。

---

## 7. 已补充实现 / 暂不修复项

### 7.1 MCP 长任务工具非阻塞化（已实现）

背景：

- FastMCP 3.x 已经通过 threadpool 执行同步函数，不存在原报告所称“同步函数阻塞整个 asyncio event loop”的直接问题，因此不按 Critical 处理。

已实现（`src/scholar_agent/server.py`）：

- 新增 `_run_blocking(fn, *, tool_name, ctx)`：在 worker 线程执行阻塞工作，提供可配置超时（`asyncio.wait_for`）、粗粒度进度上报（FastMCP `Context.report_progress`），并透传取消（MCP 原生请求取消）。
- 新增 `_tool_timeout(tool_name)`：超时优先级为 `SCHOLAR_<TOOL>_TIMEOUT` > `SCHOLAR_TOOL_TIMEOUT` > 默认值；值 <= 0 关闭超时。
- 将 `analyze_paper`、`extract_paper_images` 改为 `async def` + 嵌套 `_impl()` + `_run_blocking`；`download_paper`、`daily_recommend` 由原 `asyncio.to_thread` 接入统一 helper。四者均新增可选 `ctx: Context` 参数（FastMCP 自动注入且不污染工具 schema）。
- 测试：`tests/test_mcp_server.py` 新增 `_tool_timeout` 与 `_run_blocking`（正常/超时/无 ctx/进度上报）覆盖。

刻意未做（避免过度设计）：

- 不引入自建内存型 task/background job 注册表 + 轮询工具。在 stdio MCP 单进程下它会破坏现有工具契约、重启即丢状态，且严格劣于 MCP 原生「异步 + 进度 + 取消」机制。
- 局限性（已在代码注释说明）：worker 线程无法被强制杀死，超时/取消时请求立即返回并释放事件循环，但孤儿线程会跑完且结果被丢弃。


### 7.2 `transition_card()` 死代码

原因：

- 该函数在 `knowledge_governance.py` 中实际调用，原报告误判。

### 7.3 arXiv tar 文件未清理

原因：

- 外层临时目录会清理下载文件，原报告已标注非问题。

---

## 8. 执行顺序

1. 添加/更新测试，锁定第一批问题的期望行为。
2. 修复 HTTP auth、Content-Length、reindex path。
3. 修复 PyMuPDF 和 urllib response 资源释放。
4. 修复 schema 枚举不一致。
5. 修复 dual-track 异常隔离。
6. 修复 BM25 字段容错。
7. 引入原子写入 helper，并替换最高风险写入点。
8. 运行聚焦测试：
   - `tests/test_import_paperpulse.py`
   - `tests/test_knowledge_lifecycle*.py`
   - `tests/test_local_retrieve*.py`
   - `tests/test_academic.py` 或 daily workflow 相关测试
   - `tests/test_local_index.py`
9. 运行全量测试；若全量测试因外部依赖或慢集成失败，记录失败原因和已通过的聚焦测试。

---

## 9. 完成标准

- 第一批所有问题均有代码修复和测试覆盖。
- 原报告中已确认误判项不产生无意义代码改动。
- 导入接口在未配置 token 时只接受真实本机 peer 请求。
- 自动生成知识卡片通过生命周期 schema 校验。
- dual-track daily workflow 任一 track 失败时仍能返回另一个 track 的结果，并暴露失败原因。
- PDF/urllib 资源在异常路径可释放。
- 关键写入路径至少覆盖 index、import、knowledge card、daily note 的原子写入。
