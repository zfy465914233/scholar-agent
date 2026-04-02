---
description: "Find implementations and code repositories for a given research paper or algorithm. Use for paper-to-code mapping, finding reference implementations, locating reproducible research."
agent: "research"
tools: [web, search, read]
argument-hint: "Paper title, algorithm name, or arXiv ID"
---

查找以下论文/算法的代码实现映射：

**论文/算法**: ${input}

## 要求

1. 搜索 GitHub、Papers with Code、arXiv 和官方项目主页。
2. 对每个实现评估：是否官方实现、stars 数量、最近更新时间、许可证。
3. 标注代码与论文的对应关系（完整复现 / 部分实现 / 非官方移植）。
4. 输出结构化列表，包含所有证据来源和时间。
