## Why

工具时间线已有后端统一的双语名称和 call/result 关联，但前端对组装、渲染和其他工具使用了不一致的标题与状态呈现，且运行中或失败的工具步骤会自动展开大量原始内容。用户难以快速区分业务步骤和技术细节，需要让工具步骤清楚、克制，并在普通运行与评测中保持一致。

## What Changes

- 所有工具步骤统一优先展示现有的双语 `tool_label`，明确区分 `assemble_spec` 与 `render_chart`，阶段标签作为辅助信息。
- 工具状态使用一致的中文语义；仅将已识别的状态映射为成功、失败或阻塞，未识别状态明确显示为未知，不推断为完成或发布。
- 普通运行与评测共用的工具时间线中，参数、完整结果和技术事件默认折叠；折叠摘要保留工具名称、时间、状态及必要的失败原因。
- 生成图表等用户结果继续在结果区域直接展示，不随工具详情折叠而隐藏。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `desktop-client`: 工具时间线统一双语标题、状态语义和详情默认折叠行为，同时保留可见的失败摘要与生成结果。
- `evaluation-workbench`: 评测只读时间线复用普通运行的工具标题、状态和默认折叠规则，不另建工具展示分支。

## Impact

- 主要影响 `frontend/src/domain/run/timeline.ts`、`frontend/src/domain/display.ts`、`frontend/src/components/run.tsx`、`frontend/src/components/common.tsx` 及普通运行/评测时间线的相关前端回归测试。
- 复用后端 `tool_label` 和现有 Gateway 事件协议，不新增工具名称映射副本、API 或生命周期状态。
- 验证普通运行、运行历史、评测只读回放、运行中/失败状态、未知状态及被截断结果的呈现；生成图表最终结果保持独立可见。
