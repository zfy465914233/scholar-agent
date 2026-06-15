---
id: diffusion-model-zh
title: 扩散模型
type: knowledge
topic: generative-models
confidence: confirmed
---

# 扩散模型

扩散模型是一类基于逐步去噪的生成模型。前向扩散过程逐步向数据添加高斯噪声，反向去噪过程学习从噪声恢复数据。

DDPM（去噪扩散概率模型）是扩散模型的代表性工作。扩散模型在图像生成领域取得了突破，稳定扩散是其著名应用。

训练目标是学习去噪网络，使其能在任意噪声水平下预测并去除噪声。核心思想是建模数据分布的逐步变化。
