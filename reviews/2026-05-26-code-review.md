# Scholar Agent 仓库代码评审

- 首次评审日期：2026-05-26
- 复审日期：2026-05-26
- 评审对象：仓库当前主线
- 评审方法：静态阅读 + 聚焦运行时 smoke check + 聚焦测试执行 + 最小 wheel 构建检查

## 当前结论

本文件已根据复审结果更新，首次评审中已确认的 open issues 不再全部成立。

- 已确认修复：4 项
  - [src/scholar_agent/server.py](src/scholar_agent/server.py) 中 ingest_source 和 build_graph 的包内导入错误
  - [src/scholar_agent/engine/close_knowledge_loop.py](src/scholar_agent/engine/close_knowledge_loop.py) 的 schema 资源路径解析错误
  - [src/scholar_agent/engine/domain_router.py](src/scholar_agent/engine/domain_router.py) 的 routing 资源路径解析错误
  - [templates/mcp.json.template](templates/mcp.json.template) 的过时 MCP 启动入口
- 当前仍需继续跟进：3 项
  - 1 项高优先级运行时问题
  - 1 项中优先级打包问题
  - 1 项中优先级测试覆盖问题
- 相关窄测试 `python -m pytest tests/test_mcp_server.py tests/test_build_graph.py tests/test_domain_router.py tests/test_local_synthesis_and_loop.py -q` 当前为 `48 passed`

## 已关闭问题

### 1. 已关闭：ingest_source 和 build_graph 的运行时导入错误

状态：已修复。

证据：
- [src/scholar_agent/server.py](src/scholar_agent/server.py) 当前已改为包内导入 `scholar_agent.engine.research_harness` 和 `scholar_agent.engine.build_graph`
- 复审时直接调用 `ingest_source("https://example.com")` 与 `build_graph()`，两者均返回成功结果，不再抛出 `ModuleNotFoundError`

### 2. 已关闭：answer schema 路径解析错误

状态：已修复。

证据：
- [src/scholar_agent/engine/close_knowledge_loop.py](src/scholar_agent/engine/close_knowledge_loop.py) 当前通过 `get_repo_root()` 解析仓库根目录
- 复审时 `ANSWER_SCHEMA_PATH.exists()` 返回 `True`
- 相关测试集通过：`python -m pytest tests/test_mcp_server.py tests/test_local_synthesis_and_loop.py -q`

### 3. 已关闭：domain router 的策略、技能和 guide 文件未被实际加载

状态：已修复。

证据：
- [src/scholar_agent/engine/domain_router.py](src/scholar_agent/engine/domain_router.py) 当前通过 `get_repo_root()` 解析仓库根目录
- 复审时 `SKILL_PATH.exists()`、`POLICY_PATH.exists()`、`GUIDE_PATH.exists()` 均为 `True`
- `load_routing_policy()` 不再返回 `None`
- `load_routing_skill()` 已加载仓库内真实 routing skill，而不是 fallback prompt

### 4. 已关闭：MCP 模板入口过时

状态：已修复。

证据：
- [templates/mcp.json.template](templates/mcp.json.template) 当前已统一使用 `scholar-agent serve-mcp`

## 剩余问题

### 1. 高优先级：lazy reindex 仍然会因顶层导入失败

影响：写入知识卡后，如果索引需要自动刷新且本地没有可复用的旧索引，随后执行 `query_knowledge` 或 `build_graph` 仍可能失败，表现为“写卡成功但无法检索”。

证据：
- [src/scholar_agent/engine/close_knowledge_loop.py](src/scholar_agent/engine/close_knowledge_loop.py#L672-L675) 中的 `reindex()` 仍使用 `from local_index import write_index`
- 在隔离的临时知识库中复现：`capture_answer()` 返回成功，随后 `query_knowledge()` 返回 `Knowledge index not found and automatic refresh failed.`
- 在默认知识库 smoke check 中，`build_graph()` 虽然返回成功，但日志同时出现 `ModuleNotFoundError: No module named 'local_index'`，说明该问题只是被已有索引掩盖，没有真正消失

根因判断：首次修复覆盖了 server 层和资源路径，但 `close_knowledge_loop.reindex()` 这条自动刷新路径仍保留旧的顶层导入方式。

建议修复：
- 将该导入改为包内导入，例如 `scholar_agent.engine.local_index`
- 增加一条集成测试，覆盖“写卡 -> 标记索引 stale -> 再次查询触发 lazy refresh”路径

### 2. 中优先级：wheel 打包仍缺少运行时资源

影响：源码运行和可编辑安装基本可用，但标准 wheel 安装仍会缺少 schema、template 和 config 资源，导致非 editable 安装存在运行时风险。

证据：
- [pyproject.toml](pyproject.toml#L45-L46) 中的 package-data 仍然使用 `../../schemas/**`、`../../templates/**`、`../../config/**` 这类路径
- 复审时实际构建 wheel 并检查压缩包内容，确认以下资源均未被包含：
  - `schemas/answer.schema.json`
  - `schemas/domain_routing_policy.json`
  - `templates/mcp.json.template`
  - `config/config.yaml`

根因判断：当前 setuptools package-data 配置仍然没有正确覆盖仓库级资源。

建议修复：
- 修正 wheel 打包策略，或将运行时资源迁移到包内并通过 `importlib.resources` 访问
- 增加 wheel 内容校验，至少断言 schema 和 template 被正确打包

### 3. 中优先级：测试仍未覆盖 server 集成入口、lazy refresh 和 wheel 构建路径

影响：即使存在剩余的运行时和打包问题，现有测试仍可全部通过，CI 不能及时暴露这些回归。

证据：
- [tests/test_mcp_server.py](tests/test_mcp_server.py#L14-L14) 仍只导入 `query_knowledge`、`save_research`、`list_knowledge`、`capture_answer`
- [tests/test_build_graph.py](tests/test_build_graph.py#L12-L12) 仍只测试 `scholar_agent.engine.build_graph` 的 engine 层实现
- 仓库当前没有针对 wheel 打包内容的测试
- 复审时执行的相关窄测试全部通过，但仍然可以稳定复现上面两条问题

根因判断：测试仍偏向单模块或静态存在性检查，没有覆盖 server wrapper 到索引刷新、以及构建产物完整性这两条真实集成路径。

建议修复：
- 在 [tests/test_mcp_server.py](tests/test_mcp_server.py) 增加 `ingest_source`、`build_graph` 和 lazy refresh 路径测试
- 增加一条最小 wheel 构建校验，确认关键资源已进入发行包

## 复审验证记录

### 1. 运行时与资源路径检查

```bash
python - <<'PY'
from scholar_agent.server import ingest_source, build_graph
from scholar_agent.engine.close_knowledge_loop import ANSWER_SCHEMA_PATH
from scholar_agent.engine.domain_router import SKILL_PATH, POLICY_PATH, GUIDE_PATH, load_routing_policy, load_routing_skill, load_routing_guide

for name, fn, args in [
    ('ingest_source', ingest_source, ('https://example.com',)),
    ('build_graph', build_graph, ()),
]:
    try:
        result = fn(*args)
        print(name, 'OK', result[:200])
    except Exception as exc:
        print(name, type(exc).__name__, exc)

print('ANSWER_SCHEMA_PATH', ANSWER_SCHEMA_PATH.exists(), ANSWER_SCHEMA_PATH)
print('SKILL_PATH', SKILL_PATH.exists(), SKILL_PATH)
print('POLICY_PATH', POLICY_PATH.exists(), POLICY_PATH)
print('GUIDE_PATH', GUIDE_PATH.exists(), GUIDE_PATH)
print('policy_is_none', load_routing_policy() is None)
print('skill_prefix', load_routing_skill()[:80])
print('guide_len', len(load_routing_guide()))
PY
```

观察结果：
- `ingest_source` 与 `build_graph` 均返回成功
- `ANSWER_SCHEMA_PATH`、`SKILL_PATH`、`POLICY_PATH`、`GUIDE_PATH` 均存在
- routing skill 与 policy 已从仓库资源加载
- 但日志仍出现 `ModuleNotFoundError: No module named 'local_index'`，指向 lazy reindex 路径

### 2. 相关窄测试执行

```bash
python -m pytest tests/test_mcp_server.py tests/test_build_graph.py tests/test_domain_router.py tests/test_local_synthesis_and_loop.py -q
```

观察结果：
- `48 passed`

### 3. 临时知识库中的 lazy refresh 复现

```bash
python - <<'PY'
import json
import tempfile
from pathlib import Path

from scholar_agent.engine import scholar_config
from scholar_agent.server import capture_answer, query_knowledge

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    knowledge = root / 'knowledge'
    index = root / 'indexes' / 'local' / 'index.json'
    scholar_config._config_cache = {
        'knowledge_dir': str(knowledge),
        'index_path': str(index),
        'scholar_dir': str(root),
    }

    answer = (
        'BM25 is a probabilistic ranking function used in information retrieval systems '
        'to estimate document relevance based on term frequency, inverse document frequency, '
        'and document length normalization. This sentence is extended to exceed the minimum '
        'capture threshold and make the card creation path execute fully.'
    )
    created = json.loads(capture_answer('bm25 temp regression', answer))
    print('capture_status', created.get('status'), created.get('card_path'))
    print('stale_exists_after_create', index.with_suffix(index.suffix + '.stale').exists())
    queried = json.loads(query_knowledge('bm25'))
    print('query_payload', json.dumps(queried, ensure_ascii=False))

scholar_config.clear_cache()
PY
```

观察结果：
- `capture_answer` 返回成功
- stale marker 已创建
- `query_knowledge` 返回 `Knowledge index not found and automatic refresh failed.`

### 4. wheel 打包内容检查

```bash
rm -rf /tmp/scholar-agent-review-dist
mkdir -p /tmp/scholar-agent-review-dist
python -m pip wheel . --no-deps -w /tmp/scholar-agent-review-dist
python - <<'PY'
from pathlib import Path
import zipfile

wheel = sorted(Path('/tmp/scholar-agent-review-dist').glob('scholar_agent-*.whl'))[-1]
with zipfile.ZipFile(wheel) as zf:
    names = zf.namelist()
    for needle in [
        'schemas/answer.schema.json',
        'schemas/domain_routing_policy.json',
        'templates/mcp.json.template',
        'config/config.yaml',
    ]:
        matches = [n for n in names if needle in n]
        print(needle, matches[:5])
PY
```

观察结果：
- 上述 4 个关键资源在 wheel 中均未找到

## 修复优先级建议

1. 先修 [src/scholar_agent/engine/close_knowledge_loop.py](src/scholar_agent/engine/close_knowledge_loop.py#L672-L675) 的 lazy reindex 导入问题，并补一条 stale -> refresh 集成测试。
2. 再修 [pyproject.toml](pyproject.toml#L45-L46) 的资源打包策略，确保 wheel 包含 schema、template 和 config。
3. 扩展 [tests/test_mcp_server.py](tests/test_mcp_server.py) 与构建校验测试，覆盖 server wrapper、lazy refresh 和 wheel 内容完整性。
