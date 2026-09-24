## Context

当前系统已经有 panel handoff、四类图表测量、`MeasurementSession`/`MeasurementAttempt`、质量审计和 `assemble_spec` 门禁。现有测量结果能够指出 `baseline`、`axes`、`coverage` 或 `association` 问题，但 repair action 还停留在文本层；本设计把这些诊断接到同一条 Agent/measurement/checkpoint/trace 链路中。详细行为边界见本 change 的 delta specs，动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 用一个受控的 target 表达“在当前 panel 的哪个源图区域、针对哪些字段进行重测”。
- 保留 source-image 坐标作为唯一归因坐标，同时返回局部 crop 与 source transform，保证 overlay 和后续证据可回溯。
- 让模型决定是否执行下一次观测，让代码校验来源、父 attempt、target 合法性、幂等性、预算和 accepted 状态。
- 让重测状态可 checkpoint、可恢复、可追踪，并能用真实图表与合成夹具验证收敛和误拒绝。

**Non-Goals:**

- 不引入 SAM、OCR 或新的检测算法；target 只改变现有测量工具的搜索范围。
- 不在本 change 中实现 ChartSpec 完整布局语义或前端专用的测量详情页面。
- 不把多个未接受 attempt 的值自动拼接成一个“完整”结果；第一版以单个 accepted attempt 作为组装来源。

## Decisions

### 1. 复用现有测量工具，增加受控 target 参数

四类测量工具各自已有图表语义和 overlay。新增一个独立的 `remeasure` 工具会增加模型选择分支、来源绑定和 Gateway 兼容成本，因此采用现有工具的可选 `measurement_target` 参数。未携带 target 的调用保持原有 panel 级行为。

target 由有限字段组成：`target_id`、`panel_id`、`parent_attempt_id`、`region_kind`、`fields`、可选的 `bbox_source_px`、`source_image_size` 和 `reason`。模型只能原样传递观察结果中的 target；Agent/Gateway 通过当前 run 上下文补充并校验 attachment、session 和工具身份。

### 2. 源图坐标优先，局部坐标只作为证据细节

target 和所有对外几何仍使用源图像坐标。工具内部可以裁剪为局部图像，但结果必须同时说明 `local_image_size`、`source_image_size`、`local_to_source` 和 target。这样既能缩小检测范围，也不会让重测结果无法和首次测量、panel handoff 或 overlay 对齐。

target 必须与当前 panel 求交；越界部分被截断并产生 warning，完全无交集或无法映射则拒绝。target 不得改变授权 attachment，也不得把相邻 panel 纳入搜索范围。

### 3. 模型驱动修复，代码拥有安全边界

质量门禁失败后，Agent 将结构化 repair action 放回模型上下文。模型可以选择补充视觉观察、调用带 target 的同一测量工具、保留不确定字段或停止。代码不在模型不可见的情况下自动重复调用传感器，但会在每次调用前检查：

- 当前 run、attachment、panel 和 session 是否一致；
- `parent_attempt_id` 是否存在且属于当前 scope；
- target 是否等价重复、是否超过 repair budget；
- 调用结果是否重新经过审计。

默认每个 measurement session 最多允许 3 次 repair attempt；已有 bounded attempt history 继续限制总历史长度。预算耗尽后返回明确的非发布状态和可恢复 checkpoint。

### 4. Attempt 以替换关系为主，不做隐式跨 attempt 合并

每个 repair attempt 都保存父 attempt 和自己的完整测量结果。只有某个 attempt 的所有阻断检查通过时，`accepted_attempt` 才会移动到它。后续 `assemble_spec` 只能引用该 accepted attempt；部分字段来自不同 attempt 的组合需要未来单独设计 field-level evidence merge，本 change 不隐式实现。

重复 target 使用稳定 fingerprint 做幂等判断。相同 session、父 attempt、工具、target 和参数摘要的重复请求不得创建新的有效 attempt；不同 target 即使属于同一 panel，也必须建立清晰的父子 lineage。

### 5. Trace 只记录修复摘要，不复制图像和完整结果

为 repair request、repair result、repair rejected 和 repair exhausted 使用稳定事件类型或等价的生命周期字段。事件只携带 run、call、session、panel、attempt、parent attempt、target kind、状态、issue count 和 next action 等 bounded 摘要。完整结构化结果继续走已有 observation/checkpoint 边界，trace 截断时保留外层调用身份。

### 6. 真实评估作为实现验收层，而不是新的模型工具

评估采用 manifest 驱动的 fixture 集：合成图用于精确值和几何断言，授权真实图用于 panel 选择、旋转、标签密集和失败场景。每个样例记录预期 panel、测量工具、可接受的状态、关键 target 和是否允许 accepted。评估同时覆盖首次测量、门禁阻断、定向重测、预算耗尽、checkpoint 恢复和重复请求，避免只验证最终数值。

## Risks / Trade-offs

- **[Risk] target 过窄导致传感器失去轴或图例上下文** → 保留 panel context，target 只限制重点搜索；当所需上下文不足时返回 partial/需要 panel 级复查，不自动 accepted。
- **[Risk] 模型重复提交相同 target 造成循环** → 使用 target fingerprint、父 attempt 校验和每 session 的 repair budget，并在 trace 中发布 exhausted 状态。
- **[Risk] 局部 crop 与源图 overlay 坐标漂移** → source-image 坐标作为规范，所有 crop 必须携带可逆 `local_to_source` 映射，并对映射做边界校验。
- **[Risk] 多次测量结果被错误拼接** → accepted attempt 只允许引用一个完整审计结果；禁止本 change 内的隐式跨 attempt 合并。
- **[Risk] 真实图片包含敏感信息或造成不稳定测试** → 使用授权且脱敏的 fixture，manifest 只保存有界标识和断言；provider 调用不作为离线核心测试依赖。
- **[Risk] 新 trace 字段放大 Gateway 事件** → 沿用现有 sanitization、字段白名单和 tool-result 外层身份保留策略，不写入图像字节或完整 provider payload。

## Migration Plan

1. 先增加 target、repair action、trace 和评估数据结构，确保无 target 的旧测量和旧 checkpoint 仍可读取。
2. 再接入四类传感器的局部搜索与 Agent repair loop，默认关闭隐式合并，保留旧的 panel 级调用兼容路径。
3. 用离线 fixture 和 Gateway/Agent 回归测试验证后启用默认 repair budget；旧 checkpoint 缺少 repair 字段时按“无待处理 repair”恢复。
4. 若新 repair 链路出现问题，可通过不传 target 回退到现有 panel 级测量和 `assemble_spec` 门禁，不需要数据库迁移或 provider 配置迁移。

## Implementation Verification Notes

- 默认每个 measurement session 的 repair budget 为 3；旧的无 target 测量调用仍按原有 panel 级路径执行。
- 旧 checkpoint 缺少 `measurementSessions`、`pendingMeasurementRepair` 或 repair target 字段时按空 repair 状态恢复；新增字段均为可选。
- trace、Gateway 事件和 checkpoint 会清洗原始图片、绝对路径、密钥及 provider 原始 payload；Gateway 超限时保留调用身份和有界的 scope/repair 摘要。
- 本 change 未增加运行时依赖；验证使用仓库既有的 `agent` Conda 环境和已存在的 RapidOCR 安装。
