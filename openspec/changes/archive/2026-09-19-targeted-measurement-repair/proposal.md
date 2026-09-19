## Why

上一阶段已经建立了测量质量信封、attempt lineage 和 `assemble_spec` 门禁，但 `remeasure_required` 目前主要还是模型可读的诊断结果。系统能够发现基准线、坐标标定、覆盖或系列关联问题，却还不能稳定地把问题转换成当前 panel 内的目标区域重测，也缺少有界的修复次数和真实图表验收基线。

现在需要把“发现问题”推进到“可执行修复”，否则质量门禁可能只会阻止错误结果，却无法帮助 Agent 收敛到可接受的 ChartSpec。

## What Changes

- 为测量 issue 增加机器可执行的 repair action 和 measurement target，明确问题字段、当前 panel、源图坐标区域、父 attempt 与下一步动作。
- 让柱状图、折线图、饼图和散点图测量工具支持可选的目标区域/关注字段，在保持 panel 边界和源图坐标归因的前提下进行局部重测。
- 在同一 run、attachment 和 panel 内维护重测 attempt lineage；重测必须重新经过质量审计，不能由模型自行把结果提升为 `accepted`。
- 为 Agent 增加有界的测量修复策略：处理门禁失败、校验父 attempt、限制重复目标和最大重测次数，并在无法收敛时保留可恢复的非发布状态。
- 为重测请求、完成、拒绝和次数耗尽增加有界 trace 字段，确保前端和 Gateway 能够区分普通测量与修复测量。
- 建立真实图表链路评估基线，覆盖多面板、旋转/横向/分组/堆叠柱状图、多系列折线图、饼图和散点图，以及基准线、坐标、覆盖和关联失败场景。
- 保持现有直接视觉装配、`assemble_spec` provenance、checkpoint 恢复、幂等语义和四类图表专属结果字段兼容。

本 change 不引入 SAM/OCR 算法，不实现 ChartSpec 完整布局语义，也不把修复动作暴露为新的独立模型工具；目标区域作为现有测量工具的受控可选参数传入。

## Capabilities

### New Capabilities

- None. 本 change 扩展已有测量质量、图表观测、Agent 修复和执行追踪契约。

### Modified Capabilities

- `measurement-quality-gate`: 增加机器可执行的目标区域、repair action、重测预算和父子 attempt 约束。
- `chart-understanding`: 四类测量工具支持 panel 内目标区域重测，并返回局部/源图映射和修复归因。
- `chart-evidence-fusion`: 门禁失败可以驱动当前 panel 的定向补充证据，不得直接终止或猜测缺失值。
- `agent-loop`: 增加有界的测量修复闭环、重复目标抑制和不可收敛时的显式终止状态。
- `execution-trace`: 增加测量修复生命周期和目标区域的安全摘要，支持重连后的诊断与恢复。

## Impact

- 影响 `src/chartagent/measurement.py`、四类图表 observation 工具、Agent loop、Gateway trace 与 checkpoint 数据边界。
- 增加目标区域参数、repair action 和 repair trace 字段，但不改变已有测量字段和直接视觉 `assemble_spec` 调用方式。
- 增加真实图表/合成图表评估夹具、质量指标和端到端回归测试；评估数据只保留授权且有界的图片与标注，不写入密钥、绝对路径或 provider 原始响应。
- 不新增 Python/前端运行时依赖，不要求启用 SAM，也不改变现有 provider 配置。
