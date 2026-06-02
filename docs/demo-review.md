# Demo 准确性评审

**评审日期**: 2026-06-01  
**评审对象**: `assets/demo.gif`（175 帧，720×420px，60ms/帧）  
**评审方法**: 逐帧提取文本内容，与实际 MCP 工具行为逐项比对

---

## 总体结论

Demo 展示的是一个**捏造的独立 CLI 交互**，与 Scholar Agent 的实际架构（MCP 服务器）存在多处根本性不一致。核心问题不是细节偏差，而是交互模型本身就是错的。

---

## 逐项不一致

### 1. 交互方式

| Demo 展示 | 实际行为 |
|-----------|---------|
| 独立 CLI，`> prompt` 风格输入 | MCP 服务器，用户通过 Claude Code / VS Code Copilot / OpenCode 的自然语言界面交互 |

Demo 把 Scholar Agent 呈现为一个可以直接在终端运行的应用程序，但实际用户永远不会直接与 Scholar Agent 的 CLI 交互（`serve-mcp` 是后台服务）。用户看到的是 LLM host 的界面。

### 2. 工作流归属

| Demo 展示 | 实际行为 |
|-----------|---------|
| Scholar Agent 自身编排整个搜索流程："Searching web + arXiv + Semantic Scholar..." | LLM（Claude 等）编排工作流：先调 `query_knowledge` 查本地 → 不够时用自己的搜索工具或 `search_papers` → 最后调 `save_research` 存储 |

Scholar Agent 是被动工具提供方，不是主动编排者。Demo 暗示它是一个自包含的研究引擎，这是错误的。

### 3. 输出格式

Demo 中的以下内容都不是实际存在的输出格式：

- `Local knowledge hit! (BM25 score: 0.94)` — MCP 工具返回结构化 JSON，不会生成这样的文字
- `Response time: <0.1s (vs ~5s web research)` — MCP 工具不返回响应时间对比
- `Knowledge base: 33 cards | Growing every query` — 没有任何工具生成这种状态行
- `Saved knowledge card: mixture-of-experts.md` — `save_research` 返回确认 JSON，不是格式化文本
- `Sources: 3 papers + 2 web articles` — 不是实际输出格式
- `Confidence: high` — 不是独立输出行

MCP 工具（`query_knowledge`、`save_research`、`search_papers` 等）返回结构化数据，LLM 自己决定如何向用户呈现。用户实际看到的是 LLM host 的自然语言回复。

### 4. 营销式表达

Demo 中包含多处不当的性能暗示：

- `Response time: <0.1s (vs ~5s web research)` — 本地 BM25 检索确实快，但 LLM 生成回答才是实际瓶颈。这个对比是误导性的。
- `Knowledge base: 33 cards | Growing every query` — 暗示每次查询都自动产生新卡片，但实际上 `save_research` 需要 LLM 主动调用，不是自动的。
- 隐含了 Scholar Agent 能独立完成"搜索 → 分析 → 存储"全流程，但每个环节都需要 LLM 主动调用对应的 MCP 工具。

### 5. 学术搜索展示

Demo 中显示：
```
> search_papers("mixture of experts", top_n=5)
#1 Switch Transformers (Fedus et al., 2024)
```

实际上：
- 用户不会以函数调用语法与 Scholar Agent 交互
- `search_papers` 返回带评分的论文列表 JSON，不是格式化编号文本
- LLM 会用自然语言呈现搜索结果，不会原样输出函数调用语法

---

## 问题严重性评估

| 问题 | 严重性 | 原因 |
|------|--------|------|
| 交互方式错误 | **高** | 根本性误导——产品架构都展示错了 |
| 工作流归属错误 | **高** | 让人误以为 Scholar Agent 是自包含引擎 |
| 输出格式捏造 | **中** | 虚构了不存在的 UI/输出 |
| 营销式性能对比 | **中** | 误导性的速度对比 |
| 函数调用语法展示 | **低** | 用户不会这样交互，但不影响理解 |

---

## 建议

**删除当前 demo.gif。** 它展示的是一个不存在的 CLI 产品，与实际 MCP 服务器架构不匹配。

**替代方案（按推荐度排序）：**

1. **真实录屏** — 用屏幕录制工具录制一次 Claude Code 中的实际使用流程：用户提问 → Claude 调用 `query_knowledge` → 调用 `save_research` → 下次类似问题直接从本地知识获取答案。真实可信，不需要后期制作。

2. **Asciinema 录制** — 如果需要终端风格展示，可以用 `asciinema` 录制 `scholar-agent doctor`、`scholar-agent config show` 等 CLI 命令的实际输出。但这只展示 CLI 功能，不展示核心的 MCP 交互。

3. **架构流程图** — 用静态图展示工作流：用户 → LLM host → MCP tools → 本地知识库。不追求展示具体输出，而是展示架构和数据流。简单准确。

4. **无 demo** — 直接删除，README 的文字描述已经足够清晰。很多成功的开源项目（如 FastAPI、Pydantic）也不用 GIF demo。
