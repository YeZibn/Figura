## Why

当前生成图表的审核链路依赖 OCR、几何传感器以及主 Agent 调用
`review_generated_chart`，审核逻辑被拆散在多个工具和模型回合中，难以完整判断旋转、横向布局、标签关联和视觉语义一致性。需要让多模态 VLM 在生成后自动完成一次统一审核，同时保留代码侧的最小发布安全边界，降低遗漏审核或错误发布的风险。

## What Changes

- 增加生成图表的内部 VLM 审核阶段；每个需要审核的候选图在生成后自动触发一次无工具的额外 VLM 调用。
- 将原图（存在时）、生成候选图和不可变 ChartSpec 一起提供给审核 VLM，由 VLM 统一判断图表类型、方向、布局、数据映射、标签和可读性。
- 要求审核 VLM 返回受限的结构化结果，包括总体决策、置信度、逐项检查和定位到 ChartSpec 或图形区域的问题。
- 将审核结果固定为严格 JSON 契约：顶层只允许 `decision`、`confidence`、`checks` 和 `issues`，并明确 `pass`、`pass_with_warning` 与 `fail` 的一致性规则。
- **BREAKING** 移除主 Agent 可见的 `review_generated_chart` 审核工具及其“模型主动提交审核决定”的调用路径。
- 将确定性的检查收敛为发布安全检查：保留 ChartSpec 结构校验、PNG 解码、尺寸和空白图检查，但不再使用 OCR、CV 或图表测量传感器判断语义正确性。
- 由代码根据 VLM 结果原子地完成 `published`、`published_with_warning` 或 `rejected` 状态转换；主 Agent 不得凭自由文本绕过审核状态。
- 审核失败时将结构化问题反馈给主 Agent，允许在次数和时间预算内修正 ChartSpec 并重新生成候选图。
- 明确主 Agent 的候选图生命周期：`render_chart` 结果只能作为预览，必须依据 `publicationStatus` 判断是否可以对外声明已发布，并按结构化诊断走 `assemble_spec → render_chart` 修正链路。
- 更新 Agent 提示词、执行轨迹、Gateway 投影和前端状态展示，使审核自动执行且审核结果可追踪。
- 修正 pending、failed、timeout 和 retry-exhausted 状态的终止行为，任何未通过的候选图都不能被声明为已发布。

## Capabilities

### New Capabilities

- `vlm-chart-review`: 定义无工具 VLM 审核调用的输入、结构化输出、决策边界、失败重试和结果归因。

### Modified Capabilities

- `chart-generation`: 将源图语义一致性审核改为内部 VLM 审核，并明确确定性检查只负责发布安全边界。
- `agent-loop`: 移除主模型可见的审核工具，改为生成后自动审核，并阻止最终回答绕过失败或未完成审核。

## Impact

- 影响 `src/chartagent/agent/loop.py`、`src/chartagent/review/manager.py`、
  `src/chartagent/tools/adapters/review.py`、`src/chartagent/runtime/factory.py`
  和 `src/chartagent/runtime/prompts.py`。
- 需要扩展现有 LLM client 调用边界以记录一次内部无工具多模态调用，并隔离该调用的历史和工具面。
- 需要调整审核状态模型、执行 trace、Gateway 候选/成品投影和前端审核状态展示。
- 需要更新审核、Agent、Gateway 和提示词相关测试；不改变 `assemble_spec` 的结构化构造与校验职责。
- 运行时会为需要审核的生成图增加一次 VLM 请求、延迟和多模态 token 消耗；审核调用必须使用现有 provider 配置并遵守已有超时与重试边界。
