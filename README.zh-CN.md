# Scholar Agent

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![MCP Ready](https://img.shields.io/badge/MCP-Ready-brightgreen.svg)

[English](README.md)

> 通用大模型在专业领域常常不够准、也不够新。Scholar Agent 通过"在线研究补充 + 本地知识沉淀"形成可持续的知识飞轮，让 AI 在你的领域越用越强，也为你提供、维护人类学习的知识库。通过 MCP 无缝接入 Claude Code 与 VS Code Copilot。

## 核心机制：研究 → 沉淀 → 越用越强

大模型的训练数据是静态的。当你需要它回答专业领域或最新进展时，它只能靠通用知识猜。

Scholar Agent 给它加了一个**知识飞轮**：

```
你的提问
    │
    ▼
在线研究（AI agent 搜索 + SearXNG + 学术 API）
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

每一轮使用都在积累。知识卡片有完整的生命周期管理：**draft → reviewed → trusted → stale → deprecated**。

## 学术研究管线

Scholar Agent 内置完整的学术论文研究管线：

- **论文搜索** — 搜索 arXiv、DBLP、Semantic Scholar，支持顶会过滤（CVPR、ICCV、ECCV、ICLR、AAAI、NeurIPS、ICML、ACL、EMNLP、MICCAI）
- **智能评分** — 四维评分引擎（相关性、时效性、影响力、质量），按研究兴趣排序
- **深度分析笔记** — 自动生成 20+ 章节的 Obsidian 风格 Markdown 笔记，`<!-- LLM: -->` 占位符辅助 AI 补全
- **图片提取** — 从 arXiv 源包和 PDF 中提取论文图表
- **每日推荐** — 每日论文搜索、评分、去重、推荐笔记自动生成
- **论文 → 知识卡片** — 将论文分析转化为知识卡片，反哺知识飞轮
- **关键词自动链接** — 扫描笔记中的专业术语，自动创建 `[[wiki-links]]`

## 快速开始

### 作为独立项目使用

```bash
# 克隆并安装
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -r requirements.txt

# 构建知识索引
python scripts/local_index.py --output indexes/local/index.json

# （可选）启动 SearXNG 用于在线研究
docker compose up -d
```

MCP 配置已预置，启动即用：

- **Claude Code**：`.mcp.json` 已配好，`cd` 到项目目录启动即可
- **VS Code Copilot**：`.vscode/mcp.json` 已配好，打开项目启用 agent 模式即可

### 嵌入到已有项目

```bash
cp -r scholar-agent/ your-project/scholar-agent/
cd your-project && python scholar-agent/setup_mcp.py
```

自动生成配置。知识库在**你的项目里**，不在 scholar-agent 内部。

## MCP 工具

### 核心工具（始终可用）

| 工具 | 说明 |
|------|------|
| `query_knowledge` | 搜索本地知识库 |
| `save_research` | 保存研究结果为知识卡片（支持 Mermaid 图表、来源图片） |
| `list_knowledge` | 浏览所有知识卡片 |
| `capture_answer` | 快速捕获问答为草稿卡片 |
| `ingest_source` | 摄入 URL 或文本到知识库 |
| `build_graph` | 生成交互式知识图谱（vis.js） |

### 学术工具（设置 `LORE_ACADEMIC=1` 启用）

| 工具 | 说明 |
|------|------|
| `search_papers` | 搜索 arXiv + Semantic Scholar，四维评分 |
| `search_conf_papers` | 搜索顶会论文（DBLP + S2 增强） |
| `analyze_paper` | 生成深度分析笔记（20+ 章节） |
| `extract_paper_images` | 从 arXiv 源包 / PDF 提取图表 |
| `paper_to_card` | 将论文分析转化为知识卡片 |
| `daily_recommend` | 每日论文推荐工作流 |
| `link_paper_keywords` | 关键词自动 `[[wikilinks]]` 链接 |

## 配置

### .lore.json

`.lore.json` 配置知识库路径和学术研究设置。完整示例见 [`.lore.example.json`](.lore.example.json)。

### 环境变量

复制 `.env.example` 为 `.env` 并配置：

| 变量 | 必需 | 说明 |
|------|------|------|
| `LORE_ACADEMIC` | 否 | 设为 `1` 启用学术工具 |
| `S2_API_KEY` | 否 | Semantic Scholar API key（[免费申请](https://api.semanticscholar.org/)） |
| `LLM_API_KEY` | 否 | LLM API key（用于高级合成管线） |
| `SEARXNG_BASE_URL` | 否 | SearXNG 地址（默认 `http://localhost:8080`） |

## 项目结构

```
scholar-agent/
├── mcp_server.py              # MCP 服务器（13 个工具）
├── setup_mcp.py               # 嵌入已有项目
├── pyproject.toml             # 包配置
├── docker-compose.yml         # SearXNG
├── .lore.json                 # 项目与学术配置
├── schemas/                   # 答案 + 证据 JSON schema
├── scripts/
│   ├── academic/              # 学术研究模块
│   │   ├── arxiv_search.py    # arXiv + Semantic Scholar 搜索
│   │   ├── conf_search.py     # 顶会论文搜索（DBLP）
│   │   ├── paper_analyzer.py  # 深度分析笔记生成
│   │   ├── scoring.py         # 四维论文评分引擎
│   │   ├── image_extractor.py # PDF 图表提取
│   │   ├── note_linker.py     # Wiki-link 发现 + 关键词链接
│   │   └── daily_workflow.py  # 每日推荐管线
│   ├── lore_config.py         # 配置读取
│   ├── local_index.py         # BM25 索引构建
│   ├── local_retrieve.py      # 知识检索
│   ├── close_knowledge_loop.py # 知识卡片构建
│   └── ...                    # 研究、合成、治理、图谱
├── knowledge/                 # 知识卡片（gitignored，用户生成）
├── indexes/                   # 生成的索引（gitignored）
└── tests/                     # 247 个测试
```

## 更多特色

- **多视角研究** — 可从学术、技术、应用、对立、历史五个视角并行研究，避免单一来源偏差
- **Obsidian 兼容** — 标准 Markdown + YAML frontmatter + `[[wiki-links]]`
- **知识治理 CLI** — 校验 frontmatter、检测孤立卡片和断链、发现重复、管理生命周期
- **Provider 容错** — 各搜索源独立容错，外网不可用时仅用本地检索

## 测试

```bash
python -m pytest tests/ -v
```

247 个测试，约 13 秒。无需外部服务。

## 许可证

MIT — 见 [LICENSE](LICENSE)。
