# RAG Agent 讨论记录

Date: 2026-04-01  
Author: Fangyi / Antigravity (AI)

---

## 背景与问题陈述

**用户描述的核心困境：**

通用大模型（如 GPT-4、Claude 等）在处理以下细分领域时存在明显不足：

- QPE 算法（Quantum Phase Estimation）
- 量化算法（信号量化、神经网络量化等）
- 运筹优化（Operations Research / Mathematical Optimization）

具体表现：

1. **知识不够新**：无法获取最新论文和方法，训练数据存在截止日期限制
2. **知识不够可靠**：容易产生幻觉（hallucination），错误地"编造"公式或定理
3. **无法从基础推导**：模型只是在复述记忆，缺乏严格的演绎推理能力

**用户的目标：** 搭建一个 agent 类系统，解决上述问题，提升算法效果。

---

## 参考文档评审：`2026-04-01-local-rag-roadmap.md`

GPT 给出的路线图描述了一个 **混合本地知识 + 网络搜索 + 在线模型推理** 的系统，核心架构为：

```
用户问题
  → 编排层（Orchestrator）
  → [A] 本地知识检索  [B] 网络搜索
  → 证据合并 + 排序
  → Prompt/Context 构建
  → 在线模型推理
  → 答案 + 证据引用
  → 知识蒸馏回本地知识库
```

---

## 当前项目状态（optimizer/ 目录）

| 组件 | 现状 |
|---|---|
| `scripts/research_harness.py` | ✅ 已有：搜索/抓取/缓存/评分管道（514行） |
| `scripts/cache_helper.py` | ✅ 已有：缓存辅助 |
| `schemas/evidence.schema.json` | ✅ 已有：证据JSON schema |
| `knowledge/` 目录 | ❌ 不存在 |
| 本地检索层 | ❌ 不存在 |
| 知识卡片格式 | ❌ 不存在 |
| 证据合并层 | ❌ 不存在 |
| 知识蒸馏管道 | ❌ 不存在 |

**结论：** 当前 repo 是一个可用的 **web research harness**，距离完整 RAG 系统还差 Phase 1-5 的全部工作量。

---

## AI 观点与分析

### 1. 问题分层：失败模式诊断

在投入建设之前，先明确瓶颈所在：

| 失败模式 | 真实瓶颈 | 适合的解法 |
|---|---|---|
| 不知道最新QPE论文 | 知识陈旧 | RAG / 网络搜索 ✅ |
| 错误编造公式 | 幻觉/不可信 | 引用锚定 + 验证层 ✅ |
| 无法从基础推导 | 推理能力不足 | 换更强模型 / 思维链提示 |
| 不懂项目私有上下文 | 私有知识缺失 | 本地知识库 ✅ |

> **关键提示：** GPT 路线图主要解决前两类问题。"从基础推导"这个需求，RAG 本身并不解决，需要更强的推理模型或思维链工程设计。

---

### 2. GPT 路线图评估

**优点：**
- 三层架构设计清晰（本地记忆 / 网络时效 / 模型推理）
- 将"知识蒸馏"列为一等功能，是让系统随时间复利增值的关键设计
- 节奏合理：先稳固已有 web harness，再叠加本地 RAG

**保留意见：**

**a. 工作量可能被低估**  
每个 Phase（1-5）都不是小工程，当前 repo 距目标还很远，需要有清醒预期。

**b. RAG 对算法领域的特殊挑战**  
量化/QPE/运筹领域的知识有强结构性：
- **定理需要完整证明链**：RAG 的 chunk 切割可能打断逻辑链
- **公式需要符号一致性**：跨文档 retrieve 来的公式符号经常冲突
- **核心知识在付费论文/教材**：web search 无法抓取

**c. 缺少问题分类的决策逻辑**  
不同类型问题应走不同路径，路线图 Phase 3 提到了但细节不足。

---

### 3. 建议

#### 短期建议：先验证核心假设（1-2周）

在投入大量工程资源之前，用最小成本验证 RAG 的增益：

1. 手工整理 5-10 张知识卡片（QPE 核心概念 / 常用公式）
2. 将这些卡片直接 paste 进 prompt
3. 对比有/无知识卡片时模型回答质量的差异

- 差异明显 → RAG 方向正确，值得投入 Phase 1-5
- 差异不大 → 瓶颈在推理能力，优先考虑换模型或优化提示策略

#### 中期建议：增加"推导卡"这种知识卡片类型

在 Phase 1 的知识库设计中，针对算法领域增加专门的卡片格式：

```yaml
# 推导卡（derivation card）
type: derivation
topic: quantum_computing
title: QPE 相位估计误差界推导
prerequisites:
  - quantum_fourier_transform
  - eigenvalue_estimation
steps:
  - step: 1
    claim: "..."
    proof: "..."
    source: "arXiv:xxxx, eq.3"
executable_notebook: notebooks/qpe_error_bound.ipynb
confidence: confirmed
updated_at: "2026-04-01"
```

这样既能被 RAG 检索，又保留了从基础推导的完整逻辑。

#### 问题分类决策层（补充 Phase 3）

明确定义三类问题应走的路径：

| 问题类型 | 示例 | 推荐路径 |
|---|---|---|
| A: 最新方法/SOTA | "QPE最新改进是什么" | web-led |
| B: 从基础推导 | "这个对冲公式如何推导" | local knowledge + 强模型推理 |
| C: 代码/策略问题 | "我的策略代码哪里有bug" | 直接给模型，不需RAG |

#### 长期：遵循路线图对过早自动化的告诫

GPT 路线图 Section 9 的建议有效：先把单次问答质量做好，再考虑 IDE 插件、自动循环等复杂功能。

---

## 下一步行动项

- [ ] **验证实验**：手工整理几张知识卡片，测试 prompt-stuffing 的效果
- [ ] **设计知识卡片 schema**：涵盖 definition / method / theorem / derivation 四种类型
- [ ] **Phase 0 代码评审**：评估 `research_harness.py` 的证据字段是否达到引用标准
- [ ] **决定 Phase 1 优先级**：知识库内容先行（手工整理）还是检索层先行（工程）

---

## 参考文件

- 路线图原文：[2026-04-01-local-rag-roadmap.md](./2026-04-01-local-rag-roadmap.md)
- 当前主脚本：[research_harness.py](../scripts/research_harness.py)
