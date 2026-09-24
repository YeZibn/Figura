# Proposal: add-chartspec

## Problem Statement

ChartAgent 采用双向（理解 / 生成）架构，两条路径都需要一个共同的中间表示（IR）来交换图表的语义内容：
- **理解侧**把一张图片还原成可编辑、可复用的数据。
- **生成侧**把数据渲染成图表。

目前没有这个 IR，理解侧触达的第一个产物无处落地，生成侧也无统一的输入契约。两个方向各自定义数据结构会导致接口漂移、无法互相复用。

## Goals

- 定义 `ChartSpec`：一个序列化友好的、文档化良好的 schema，作为理解与生成两侧共享的中间表示。
- 仅定义 schema 与契约（数据模型 + 校验规则），本轮**不实现**任何理解/生成算法。
- 契约可测绘：任一能力之间通过 `ChartSpec` 收发数据，字段与约束有明确定义。

## Non-Goals

- 不实现 OCR / CV / VLM 等理解侧算法。
- 不实现渲染后端或代码生成。
- 不接入数据库或持久化。
- 不定义理解侧流水线各阶段（那是后续单独 change）。

## Proposals

### Option A（选用）：数据类 `ChartSpec` + 内置校验

在本仓库 `src/chartagent/spec/chartspec.py` 提供：
- `ChartSpec` 数据类：包含图表元信息、坐标轴、数据集。
- `ChartType` 等枚举。
- `ChartSpec.from_dict` / `to_dict` 的序列化契约。
- `validate()` 返回结构化的校验问题列表（而非抛裸异常）。

优势：与项目现有纯 Python 风格一致，无外部依赖，可被两侧直接 import；人类可读、可测试。权重依据：项目约束要求 `ChartSpec` 作为 IR 共享于两侧，数据类是成本最低且可扩展的形式。

### Option B：Pydantic 模型

利用 pydantic 做 schema + 校验。优势：自动序列化/校验能力更强；劣势：引入新依赖，与现有无 pydantic 的代码风格不符，且属于过早优化。

**决策**：采用 Option A，保持零新依赖，schema 以字段与 `validate()` 显式表达。

## Downstream

本 change 定稿后，`ChartSpec` 的第一个消费者是后续 change `add-chart-understanding`：以 agent 可调用工具（`chart_to_spec`）的形态实现理解侧 U0（带数字标注的柱状图 → ChartSpec），届时用真实还原结果反向检验 schema 是否够用。

## Capabilities

- `chartspec`