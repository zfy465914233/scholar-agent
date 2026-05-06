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
在线研究（LLM 网络搜索 + 学术 API）
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

### 第 1 步：安装

```bash
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -e .
```

### 第 2 步：选择模式

#### 模式 A：全局（推荐）

所有项目共享一个知识库。数据存储在 `~/scholar/`。

```bash
scholar-agent init
```

MCP 注册到 `~/.claude.json`（用户级），Scholar Agent 在**所有项目**中可用。

#### 模式 B：项目级（独立知识库）

每个项目拥有独立的知识库，存储在项目目录内。知识卡片可与代码一起进行版本管理。

```bash
cd my-project
SCHOLAR_HOME=$(pwd)/scholar scholar-agent init    # macOS / Linux

# Windows (PowerShell)
# $env:SCHOLAR_HOME = "$PWD\scholar"
# scholar-agent init
```

数据存储在 `my-project/scholar/`。MCP 注册到 `my-project/.mcp.json`（项目级），**仅在该项目**中可用。

如果不想将知识卡片纳入版本管理，将 `scholar/` 加入 `.gitignore`；否则可以直接提交以与团队共享。

#### 模式 C：开发者 / 贡献者

```bash
git clone https://github.com/zfy465914233/scholar-agent.git
cd scholar-agent
pip install -e .
scholar-agent config init
python -m pytest tests/ -v
```

## CLI 命令参考

| 命令 | 说明 |
|------|------|
| `scholar-agent init` | 一键设置：数据目录 + 配置 + MCP 注册 |
| `scholar-agent serve-mcp` | 启动 MCP 服务器（Claude Code 内部调用） |
| `scholar-agent doctor` | 查看环境与配置诊断信息 |
| `scholar-agent config show` | 显示解析后的配置 |
| `scholar-agent config init` | 创建用户级数据目录和配置 |
| `scholar-agent config migrate --to user-home` | 从旧目录布局迁移数据 |
| `scholar-agent install claude --write` | 注册 MCP 到 Claude Code |
| `scholar-agent install vscode --write` | 注册 MCP 到 VS Code Copilot |
| `scholar-agent install opencode --write` | 注册 MCP 到 OpenCode |
| `scholar-agent install claude --status` | 检查 Claude Code 是否已注册 MCP |
| `scholar-agent install claude --uninstall` | 从 Claude Code 移除 MCP 注册 |

## 数据目录

| 模式 | 默认路径 |
|------|---------|
| 全局 | `~/scholar/` |
| 项目级 | `my-project/scholar/` |

可通过 `SCHOLAR_HOME` 环境变量覆盖。

```
init 后的目录结构：
  scholar/
  ├── config/         # 配置文件
  ├── knowledge/      # 知识卡片
  ├── paper-notes/    # 论文分析笔记
  ├── daily-notes/    # 每日论文推荐
  ├── indexes/        # BM25 搜索索引
  ├── cache/          # 缓存数据
  └── outputs/        # 生成输出
```

## 系统依赖

| 依赖 | macOS | Ubuntu / Debian | Windows |
|------|-------|----------------|---------|
| Python 3.10+ | `brew install python` | `sudo apt install python3` | [python.org](https://www.python.org/downloads/) |

PDF 文本和图片提取由 PyMuPDF 处理（`pip install -e .` 会自动安装）。

## 推荐工作流

为获得最佳分析质量，建议按以下顺序操作：

1. **下载论文**：`download_paper("2510.24701", title="Paper Title", domain="LLM")`
2. **提取图片**：`extract_paper_images("2510.24701")`（自动检测本地 PDF）
3. **深度分析**：`analyze_paper(paper_json)`（自动检测本地 PDF，提取全文）

> **提示**：在分析前下载 PDF 可以启用全文提取，生成包含具体数据、公式和实验结果的高质量笔记。没有本地 PDF 时，分析仅基于摘要。

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

### 学术工具（设置 `SCHOLAR_ACADEMIC=1` 启用）

| 工具 | 说明 |
|------|------|
| `search_papers` | 搜索 arXiv + Semantic Scholar，四维评分 |
| `search_conf_papers` | 搜索顶会论文（DBLP + S2 增强） |
| `download_paper` | 下载论文 PDF 到本地 |
| `analyze_paper` | 生成深度分析笔记（20+ 章节） |
| `extract_paper_images` | 从 arXiv 源包 / PDF 提取图表 |
| `paper_to_card` | 将论文分析转化为知识卡片 |
| `daily_recommend` | 每日论文推荐工作流 |
| `link_paper_keywords` | 关键词自动 `[[wikilinks]]` 链接 |

## 配置

### .scholar.json

`.scholar.json` 配置知识库路径和学术研究设置。完整示例见 [`.scholar.example.json`](.scholar.example.json)。

主要配置项：
- `knowledge_dir` — 知识卡片目录路径
- `index_path` — BM25 搜索索引路径
- `academic.research_interests` — 研究领域、关键词和 arXiv 分类
- `academic.scoring` — 论文评分权重与维度

### 环境变量

复制 `.env.example` 为 `.env` 并配置：

| 变量 | 必需 | 说明 |
|------|------|------|
| `SCHOLAR_ACADEMIC` | 否 | 设为 `1` 启用学术工具 |
| `SCHOLAR_HOME` | 否 | 覆盖数据目录（默认 `~/scholar/`） |
| `S2_API_KEY` | 否 | Semantic Scholar API key（[免费申请](https://api.semanticscholar.org/)） |
| `LLM_API_KEY` | 否 | LLM API key（用于高级合成管线） |

## 项目结构

```
scholar-agent/
├── mcp_server.py              # MCP 服务器（14 个工具）
├── setup_mcp.py               # 嵌入已有项目
├── pyproject.toml             # 包配置
├── .scholar.example.json      # 带注释的配置示例
├── schemas/                   # 答案 + 证据 JSON schema
├── templates/                 # 配置与 MCP 注册模板
├── skills/                    # （已移除 — 功能在 scripts/academic/ 中）
├── scholar_agent/             # Python 包（CLI、安装器、配置）
│   ├── cli.py                 # CLI 入口
│   ├── installers/            # Claude/VSCode/OpenCode 的 MCP 注册
│   └── config/                # 配置加载、路径、用户配置
├── scripts/
│   ├── academic/              # 学术研究模块
│   │   ├── arxiv_search.py    # arXiv + Semantic Scholar 搜索
│   │   ├── conf_search.py     # 顶会论文搜索（DBLP）
│   │   ├── paper_analyzer.py  # 深度分析笔记生成
│   │   ├── scoring.py         # 四维论文评分引擎
│   │   ├── image_extractor.py # PDF 图表提取
│   │   ├── note_linker.py     # Wiki-link 发现 + 关键词链接
│   │   └── daily_workflow.py  # 每日推荐管线
│   ├── scholar_config.py       # 配置读取
│   ├── local_index.py         # BM25 索引构建
│   ├── local_retrieve.py      # 知识检索
│   ├── close_knowledge_loop.py # 知识卡片构建 + 质量门控
│   └── ...                    # 研究、合成、治理、图谱
└── tests/                     # 266 个测试
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

266 个测试，约 6 秒。无需外部服务。

## 许可证

MIT — 见 [LICENSE](LICENSE)。
