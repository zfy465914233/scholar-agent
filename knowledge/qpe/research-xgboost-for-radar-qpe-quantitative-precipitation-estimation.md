---
id: research-xgboost-for-radar-qpe-quantitative-precipitation-estimation
title: Research Note — XGBoost for radar QPE quantitative precipitation estimation
type: method
topic: qpe
tags:
  - ml-qpe
  - xgboost
  - radar
  - research-note
source_refs:
  - https://www.sciencedirect.com/science/article/abs/pii/S1364682624000038
  - https://arxiv.org/html/2410.21484v1
  - https://en.wikipedia.org/wiki/Machine
  - https://pmc.ncbi.nlm.nih.gov/articles/PMC11314722/
  - https://ieeexplore.ieee.org/document/11408195/
  - https://ieeexplore.ieee.org/document/10043123
  - https://www.nature.com/articles/s41598-026-41501-7.pdf
  - https://www.britannica.com/technology/machine
  - https://link.springer.com/article/10.1007/s00521-025-11646-z
  - https://www.mdpi.com/2072-4292/16/24/4713
confidence: draft
updated_at: 2026-04-02
origin: web_research_with_synthesis
review_status: draft
---

## Question

XGBoost for radar QPE quantitative precipitation estimation

## Answer

XGBoost 是目前雷达 QPE 反演中最有效的机器学习方法之一。多篇 2024-2026 年的论文证实 XGBoost 在降水估计中显著优于传统 Z-R 关系，尤其在多传感器融合和非线性关系建模方面表现突出。最佳实践是 XGBoost + 偏振雷达多特征输入（Z_H, Z_DR, K_DP, VIL, ET, CC），配合雨量计做偏差校正和标签。

