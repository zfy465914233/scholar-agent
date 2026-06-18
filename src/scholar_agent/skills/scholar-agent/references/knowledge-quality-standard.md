# 知识沉淀质量标准(Knowledge Sedimentation Quality Standard)

> 版本 v1.0 | 2026-06-17
> 目的:定义「最好的知识沉淀」的标准与落地机制。所有 knowledge 卡按此生产;scholar-agent 工具按此演进。
> 背景:用户痛点——knowledge 卡「没实用价值,还得自己上网查」。根因诊断见 `../ISSUES.md` F 组(save_research 是无源摘要存储器)。

---

## 一、八维标准

分两类:**内容标准**(卡本身的质量,4 维)+ **系统标准**(沉淀系统的能力,4 维)。

### 内容标准

#### 1. 准确性 accuracy
- **定义**:信息正确、有据、不杜撰。
- **为什么**:错知识比没知识更糟(实测 glm-4.7 预填曾编造 "GPT-J LAMA Avg 18.2" 等假数据)。
- **衡量**:关键数字逐项核对源(锚 Table / 原文);`confidence` 分级(high / medium / low);存疑点显式标注。
- **落地**:① 抓一手原文(webReader / analyze_paper)→ 核对;② 每条数字带 source 锚;③ `confidence` 字段 + 存疑标记。

#### 2. 实时性 freshness
- **定义**:信息当下新,过期可见。
- **为什么**:AI 领域月级变化,「不够新」是高频不满。
- **衡量**:`source_years` + `updated_at`;超期 `stale` 标记;明示「未覆盖」范围。
- **落地**:① frontmatter 标 `source_years` + `info_freshness`;② 定期 webSearch 刷新;③ stale 检测(如 source >12 月且领域快变)。

#### 3. 详实性 completeness
- **定义**:一手内容 inline,密度够,**看卡能独立解答,不用再查网**。
- **为什么**:核心痛点——「还得自己上网查」。
- **衡量**:一手内容占比;每 section 字数阈值;「看卡不用查网」自检。
- **落地**:① webReader 抓全文 → 关键片段 inline;② 不只给结论,带原文 / 数字 / 机制 / 局限。

#### 4. 可用性 utility(actionability)
- **定义**:能直接指导行动 / 决策。
- **为什么**:详实是「信息量」,可用是「能否即用」(入行参考 = 可用)。
- **衡量**:可执行步骤 / 决策建议 / checklist;「读完能做什么」。
- **落地**:① 每卡含 action 部分(路径 / 步骤 / 决策树);② 面向问题,不纯描述。

### 系统标准

#### 5. 标准化 standardization
- **定义**:格式 / 结构 / frontmatter 统一。
- **为什么**:可机器处理、可扩展、可校验。
- **衡量**:统一模板 + 质量门(像 paper-notes 的 `validate_note.py`)。
- **落地**:① knowledge 卡统一模板;② knowledge validator(新,校验八维)。

#### 6. 可溯源 traceability
- **定义**:每条论断能追到一手资料。
- **为什么**:准确性的机制保证;「不查网」的根基——没有溯源,准确性无法核实。
- **衡量**:出处网;每条锚 paper-note / 网页 / 数据;引文带原文片段。
- **落地**:① `source_notes` wikilink;② 引文锚(原文片段 + 来源);③ 网页快照存档(防链接失效);④ **易失效源**(招聘 JD、招聘页等)抓取时必记 `captured_at`,信息**归纳进卡**而非仅存 URL——DJI JD 2026-06 实证:链接失效但归纳的岗位要求仍有用。

#### 7. 可发现 discoverability
- **定义**:能高效检索 + 关联。
- **为什么**:沉淀找不到 = 白沉淀(对应 ISSUES E 组关系层)。
- **衡量**:BM25 命中 + 关系网 + query 验证。
- **落地**:① `query_knowledge` 索引;② `link_paper_keywords` 关系;③ 标签 / 分类 / 双链。

#### 8. 可演进 maintainability
- **定义**:能增量更新,有生命周期。
- **为什么**:知识会变,不能整体作废。
- **衡量**:版本号;增量更新;changelog。
- **落地**:① `version` 字段;② 局部刷新流程(只更新过期 section);③ 生命周期(创建 → 更新 → 归档)。

> **核心判断**:内容 4 维是「卡的质量」,系统 4 维是「卡为什么有用、能持续有用」。准确性是结果,可溯源是机制;详实是量,可用是落地。光满足前 4 维,卡片仍是「漂亮的死知识」。

---

## 二、标准 → 工具能力映射(及 scholar-agent 缺口)

| 标准 | 需要的能力 | 现状 | 缺口(ISSUES) |
|---|---|---|---|
| 准确性 | 抓一手 + 核对 | 论文有(analyze_paper);网页有 webReader | knowledge 卡无核对流程 |
| 实时性 | 定时刷新 + stale 检测 | 无 | F4 |
| 详实性 | 抓全文 inline | webReader 存在但未用于卡 | F3 |
| 可用性 | action 结构 | 无(纯描述) | 新增设计 |
| 标准化 | 模板 + validator | paper-notes 有,knowledge 无 | F2 |
| 可溯源 | 出处网 + 快照 | 部分(wikilink) | F1 / E1 |
| 可发现 | 索引 + 关系 | BM25 有,关系弱 | E2 / E3 / E6 |
| 可演进 | 版本 + 增量 | 无 | F4 |

**结论**:八维里,**可用性、标准化(knowledge validator)、实时性(stale)、可演进(版本)** 是当前 scholar-agent 完全缺失的——这是 save_research 改造的目标(从「无源摘要存储器」升级为「有源、可校验、可演进的知识生产器」)。

---

## 三、knowledge 卡生产流程(按八维标准)

1. **定 query + 用途**(可用性先想:这张卡读完能指导什么行动?)。
2. **抓一手**(webReader 抓网页 / analyze_paper 论文 / 复用已有 paper-note)——准确性 + 详实性 + 可溯源。
3. **inline 关键原文 / 数字 / 机制**,每条锚 source——详实性 + 可溯源。
4. **加 action 部分**(路径 / 步骤 / 决策)——可用性。
5. **标 `source_years` + `updated_at` + `confidence` + `info_freshness`**——实时性 + 准确性。
6. **挂 `source_notes` wikilink**——可发现 + 可溯源。
7. **跑 knowledge validator(八维)**——标准化。
8. **落盘 + 刷索引**——可发现。

> 步骤 7 的 validator 当前不存在(待建,F2);步骤 2-3 的「抓全文 inline」当前靠人工调 webReader(save_research 不做)。流程是目标态,标出哪步待工具支持。

---

## 四、与 paper-notes 的关系

paper-notes(论文级笔记)是 **一手资料的沉淀**(准确性 + 可溯源强,经 validate_note.py 硬校验);knowledge 卡是 **跨资料的综合 + 行动指引**(可用性 + 详实性强)。knowledge 卡应**挂载** paper-notes 作一手出处(source_notes wikilink + inline 关键片段),而非另起炉灶做摘要。两者构成:paper-notes(深)→ knowledge 卡(广 + 用)的两层结构。
