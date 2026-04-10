# Lore Agent

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![MCP Ready](https://img.shields.io/badge/MCP-Ready-brightgreen.svg)

> 通用大模型在专业领域的知识不够优、不够新。Lore Agent 通过**在线研究补充 + 本地知识库沉淀**实现知识治理，让 AI 在你的领域越用越强。

## 核心机制：研究 → 沉淀 → 越用越强

大模型的训练数据是静态的。当你需要它回答专业领域或最新进展时，它只能靠通用知识猜。

Lore Agent 给它加了一个**知识飞轮**：

```
你的提问
    │
    ▼
在线研究（SearXNG + 学术 API，多视角并行检索）
    │
    ▼
结构化合成（带引用来源、置信度、不确定性标注）
    │
    ▼
本地沉淀（Markdown 知识卡片 + BM25 索引）
    │
    ▼
下次提问时，AI 先查本地 ──命中?──► 直接用，快且准
    │ 未命中
    ▼
再次在线研究 → 沉淀 → 索引更新 ──► 知识库持续增长
```

每一轮使用都在积累。第一次问某个领域的问题需要在线研究，第二次问相关问题时，AI 直接从你的本地知识库里拿，又快又准。

知识卡片有完整的生命周期管理：**draft → reviewed → trusted → stale → deprecated**。过时的知识会被标记，新研究会覆盖旧结论。

## Quick Start

```bash
# Clone and install
git clone https://github.com/zfy465914233/lore-agent.git
cd lore-agent
pip install -r requirements.txt

# Build the knowledge index
python scripts/local_index.py --output indexes/local/index.json

# (Optional) Start SearXNG for web research
docker compose up -d
```

通过 MCP 接入 Claude Code 和 VS Code Copilot——配置已预置，启动即用：

- **Claude Code**：`.mcp.json` 已配好，`cd` 到项目目录启动即可
- **VS Code Copilot**：`.vscode/mcp.json` 已配好，打开项目启用 agent 模式即可

### 嵌入到已有项目

```bash
cp -r lore-agent/ your-project/lore-agent/
cd your-project && python lore-agent/setup_mcp.py
```

自动生成配置。知识库在**你的项目里**，不在 lore-agent 内部。

## MCP 工具

AI agent 通过 6 个 MCP 工具与知识库交互：

| 工具 | 说明 |
|------|------|
| `query_knowledge` | 搜索本地知识库 |
| `save_research` | 保存研究结果为知识卡片（支持 Mermaid 图表、来源图片） |
| `list_knowledge` | 浏览所有知识卡片 |
| `capture_answer` | 快速捕获问答为草稿卡片 |
| `ingest_source` | 摄入 URL 或文本到知识库 |
| `build_graph` | 生成交互式知识图谱（vis.js） |

## 特色能力

在核心飞轮之外，Lore Agent 还有一些区别于其他项目的能力：

**自有检索引擎** — 不依赖 LLM 读文件，自建 BM25 索引 + 可选语义 embedding 混合检索，离线可用。

**结构化答案** — 不是返回原始文本。每个答案都有 claims（带证据 ID）、inferences、uncertainty、missing evidence、visual aids，按 JSON schema 校验。

**知识图谱** — 卡片之间通过 `[[wiki-links]]` 互联，自动计算反向链接。`build_graph` 生成可交互的 vis.js 可视化。保存卡片时自动提取实体并检测与已有卡片的潜在矛盾。

**多视角研究** — 可从学术、技术、应用、对立、历史五个视角并行研究同一问题，避免单一信息来源的偏差。

**知识治理 CLI** — 校验 frontmatter、检测孤立卡片和断链、发现重复、管理卡片状态流转：

```bash
python scripts/knowledge_governance.py lint        # 孤立/断链/过期检测
python scripts/knowledge_governance.py duplicates  # 重复卡片检测
python scripts/knowledge_governance.py transition --card-id <id> --state reviewed
```

**搜索扩展** — 除自有 provider（SearXNG、OpenAlex、Semantic Scholar），还支持通过 `ExternalCandidateBatch` 注入宿主侧搜索结果（如 Claude Code WebSearch），合并进统一的证据管线。

## 与同类项目对比

| | Lore Agent | Prompt-based Wiki (e.g. llm-wiki-agent) |
|---|---|---|
| **检索** | 自有 BM25 + embedding，离线可用 | 依赖 LLM `grep`/读文件，无索引 |
| **知识生命周期** | draft → reviewed → trusted → stale → deprecated | 无——文件就是文件 |
| **知识飞轮** | 研究 → 沉淀 → 复用 → 越用越强 | 单向：LLM 写，人读 |
| **答案质量** | 结构化 JSON：claims + 证据 ID + 不确定性 | 原始文本 |
| **图谱与互联** | `[[wiki-links]]`、反向链接、vis.js 图谱 | 基于文件夹，无交叉引用 |

## 项目结构

```
lore-agent/
├── mcp_server.py              # MCP server（6 tools）
├── setup_mcp.py               # 嵌入已有项目
├── docker-compose.yml         # SearXNG
├── requirements.txt
├── schemas/                   # Answer + evidence JSON schemas
├── scripts/                   # 检索、研究、合成、治理、图谱
├── knowledge/                 # 知识卡片（Markdown + YAML frontmatter）
├── indexes/                   # 生成的索引（gitignored）
└── tests/                     # 192 tests, ~5s
```

## Benchmark

```bash
python scripts/run_eval.py --dry-run
```

| Metric | Score |
|---|---|
| Route accuracy | 100% (8/8) |
| Retrieval hit rate | 100% (8/8) |
| Min citations met | 100% (8/8) |
| Errors | 0 |

## License

MIT — see [LICENSE](LICENSE).
