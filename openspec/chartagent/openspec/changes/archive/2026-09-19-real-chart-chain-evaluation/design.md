## Context

项目已经具备附件、Gateway run、事件历史、panel handoff、测量质量门、修复 lineage、ChartSpec/figure 产物和前端事件展示。现有离线测试能够验证这些契约，但真实 provider 运行还缺少一份能回答“哪个阶段先出问题”的诊断结果。

本变更只在现有生产链路旁增加一个轻量观察层：提交少量真实样本，读取同一 run 的事件和稳定引用，生成阶段时间线和诊断报告。它不复制测量、修复或 assemble 逻辑，也不替代 Gateway 的运行状态。

## Goals / Non-Goals

**Goals:**

- 通过现有附件和 Gateway 入口完成少量真实图片的人工触发运行。
- 从已有事件中还原分区、面板交接、测量、审核、修复、assemble 和 render 阶段。
- 识别重复拆分、未作用域整图测量、审核后未修复和最终装配遗漏等问题。
- 生成有界、脱敏、可人工阅读的 JSON/Markdown 诊断结果。

**Non-Goals:**

- 不建立通用 IoU、数值误差、准确率或跨 provider 回归框架。
- 不新增评测数据库、生产 API、前端评测控制台或自动 CI 外部调用。
- 不修改 VLM prompt、图表测量算法、质量门、ChartSpec 或渲染规则。
- 不把本次少量真实运行结果当作稳定 benchmark 或模型排名依据。

## Decisions

### 1. 运行入口复用 Gateway，不自动化浏览器操作

诊断器使用现有附件上传、run 创建和事件历史边界提交样本。它可以通过脚本调用与前端相同的 Gateway API，并在必要时读取 SSE 或终态历史；不直接实例化内部工具作为端到端入口。

这样可以覆盖真实的附件授权、run 绑定、panel handoff、事件记录和产物引用，同时避免为本次 change 引入脆弱的浏览器自动化。浏览器上传和展示仍由现有前端负责，若未来需要验证 UI 行为，再单独增加 UI E2E change。

### 2. 样本清单只保留诊断所需信息

首版只登记两类真实图片：一张多面板图片和一张折线图图片。每项保存 `case_id`、相对资源引用、内容指纹、provider/model 配置摘要和人工核对用的预期面板信息。

预期面板信息可以是数量、名称和粗略区域，不要求为所有字段建立数值真值。它的作用是帮助确认“有没有漏面板、是否测量了正确区域”，不是计算准确率。

### 3. 用阶段账本归一化已有事件

诊断器将已有 run 事件按固定阶段投影：

```text
input → decomposition → panel_handoff → measurement
      → quality_review → repair → assembly → render
```

每个阶段输出状态、事件 sequence、关联的 panel/attempt/artifact ID 和有限错误摘要。阶段状态只使用 `completed`、`failed`、`not_reached`、`not_observed` 等诊断状态；Gateway 的原始生命周期状态仍是事实来源。

阶段投影使用事件中的稳定引用而不是自由文本推断。对于未绑定 `panel_id` 的多面板测量、重复 decomposition 或已接受测量没有进入最终产物的情况，账本保留异常标记，供报告归因。

### 4. 报告以 JSON 为事实、Markdown 为视图

JSON 保存样本、run、provider/model、阶段状态、事件引用、产物引用、错误归因和脱敏后的摘要；Markdown 从同一 JSON 生成，展示时间线和第一失败阶段。报告不计算总分，也不输出没有基准支撑的准确率。

脱敏复用已有事件边界：不保存 API key、Authorization 头、绝对本地路径或未经授权的原始图片内容；需要预览时只保留受控附件/产物引用和内容指纹。

### 5. 用“第一可证实失败”而不是最终画面猜因

诊断器按阶段顺序寻找第一个明确失败或契约异常：分区异常归为 `decomposition`，面板未绑定归为 `panel_routing`，区域正确但测量异常归为 `measurement`，修复未完成归为 `repair`，最终产物缺失归为 `assembly_render`，Gateway/事件异常归为 `transport_runtime`。无法从事件确认时使用 `unknown` 并说明缺少的证据。

该规则的目的不是自动裁决模型质量，而是先把真实运行中的问题分层，避免将所有不完整结果都归因到 VLM。

## Risks / Trade-offs

- [真实 provider 输出不稳定] → 只做人工触发的诊断，不做模型排名或稳定准确率结论，并记录 provider/model。
- [没有数值真值] → 只诊断链路状态、面板使用和产物完整性；数值质量留给后续 benchmark change。
- [事件历史不完整或过期] → 保留已读取的阶段，未确认部分标记 `not_observed`/`unknown`，不补造结论。
- [诊断层与生产事件语义漂移] → 复用现有事件 kind、sequence、panel/attempt/artifact 引用，并用固定事件样例测试投影。
- [报告泄露敏感信息] → 只输出受控引用和脱敏摘要，禁止将原始密钥、绝对路径或完整响应写入报告。

## Migration Plan

1. 增加最小样本清单和离线清单校验。
2. 增加 Gateway 真实运行适配和阶段事件投影，先用固定事件样例验证。
3. 增加 JSON/Markdown 诊断报告和第一失败归因测试。
4. 使用两张真实图片各人工运行一次，复核报告是否能回答当前的拆分、路由、测量、修复和装配问题。
5. 如果诊断结果证明需要数值准确率或多模型比较，再另建完整评测 change；本 change 不需要迁移或回滚生产数据。
