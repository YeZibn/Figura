# Change: Runtime timeline and error context hardening

## Why

真实运行暴露出三类相互放大的问题：普通的 run/turn/operation 生命周期事件缺少统一关联，前端因此把一条运行记录拆成大量“历史记录（关联不可用）”卡片；确定性的 provider 拒绝会被误判为不确定操作，导致恢复链路直接阻塞，却没有把余额不足等可行动原因清楚呈现；图表测量工具的 `generation_context` 在模型可见 schema 中可以通过，但运行时仍可能因缺少 `source_scope` 失败，造成测量与后续装配脱节。

这些问题让 test5 这类运行难以判断真正的失败阶段，也使普通运行、重连/重试和评测工作台看到的过程不一致。本变更统一补齐运行时关联、错误上下文和 source scope 合同，让主链路能够保留模型决策边界，同时让用户看到可定位、可恢复或明确不可恢复的结果。

## What Changes

- 为未携带 decision-unit 关联的生命周期事件建立兼容性的过程级投影：优先使用既有 unit、turn、operation 关联，无法关联时收敛到有界的 legacy 容器，而不是为每个事件创建独立顶层卡片。
- 为 model、tool、run terminal 事件保留安全、结构化的错误类别、provider 状态和用户可读原因；区分确定性 provider 拒绝与远端结果未知的暂态/不确定失败，只有后者进入 recovery-blocked 语义。
- 收紧 `generation_context` 与 source-linked measurement/assembly 的契约，使 schema、工具运行时校验和已授权的 panel/source scope 一致；不让工具替模型决定系列语义，也不允许缺失 scope 时静默扩大到整图。
- 让普通运行、重连后的历史和评测工作台复用同一套关联与错误投影，并补充包含真实生命周期事件、失败事件和 source-scope 错误的回放覆盖。

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `unified-decision-review-timeline`: 增加运行/过程/legacy 事件的有界兼容投影，保留真实失败上下文，并确保重复与重放不制造额外顶层单元。
- `execution-trace`: 补充生命周期事件的过程关联、结构化错误上下文和确定性/不确定性失败语义。
- `desktop-client`: 将过程事件聚合为可读时间线，完整展示 provider 错误和 source-scope 工具错误，并保持原始详情可展开。
- `evaluation-workbench`: 评测只读视图与普通运行使用同一投影和错误展示，不再丢失中间失败原因。
- `run-lifecycle-reliability`: 明确确定性 provider 拒绝的终态处理与不确定操作的恢复阻塞边界。
- `tool-system`: 统一 `generation_context`、`source_scope` 和 measurement/assembly 的条件约束，避免 schema 通过而运行时失败。
- `measurement-quality-gate`: 保证测量 evidence 始终绑定有效 source/panel scope，并将 scope 缺失或不一致作为可定位的局部错误。

## Impact

- 影响后端运行事件、模型调用错误分类、图表工具参数校验和时间线投影；不改变 ChartSpec 的业务语义选择权。
- 影响前端普通运行与评测运行的 timeline 分组、错误摘要和详情展开；原始 event history 仍是事实来源并保持可追溯。
- 需要更新相应的 Python/TypeScript 测试夹具与回放测试，覆盖旧事件兼容、test5 风格失败、重连/重试和 source-scope 校验。
- 不引入新的 provider 或持久化存储；错误展示需继续遵守敏感信息脱敏和有界 payload 约束。
