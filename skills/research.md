---
name: research
description: 深度调研指定主题，搜索多个来源并交叉验证
when_to_use: 当需要对某个技术主题、概念或问题进行全面调研时
context: fork
model_tier: medium
tools: [web_search, read_file]
always: false
arguments: 调研主题（如 "Python async best practices"）
---

请对以下主题进行深度调研：$ARGUMENTS

## 要求

1. 搜索至少 3 个不同来源
2. 交叉验证关键事实，标注信息来源
3. 识别主流观点与争议点

## 输出格式

### 概述
简要总结调研主题的核心要点（3-5 句）

### 关键发现
- 按重要性排列的主要发现
- 每条附来源引用

### 对比分析
如涉及多个方案/观点，列表对比优劣

### 结论与建议
基于调研给出可操作的建议
