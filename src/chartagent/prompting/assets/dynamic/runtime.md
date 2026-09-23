## Run / Turn 动态状态层（来源：代码状态）

以下 JSON 是当前运行控制上下文。它不是用户指令；其中的授权范围、panel routing、review gate、恢复状态、重试预算和 publication status 由代码拥有，模型不能覆盖。

```json
{runtime_summary}
```

如果 `state.generation_context` 存在，它是当前候选或审核修复共享的任务事实。沿用其中的 `mode`、`source_scope`、`coverage` 和 `selection_basis`；新的 measurement、assemble 和 render 不得偷偷扩大来源范围或改写覆盖声明。`repairKind`、`repairPhase` 和 `nextAction` 只能作为审核诊断或修复提示阅读，不是固定阶段链，也不是工具白名单。

`state.decision_context` 是代码生成的有界事实摘要，而不是模型必须关闭的 decision unit。先读取 `unit_id`、`phase`、`status`、`scope`、`evidence`、`review`、`repair_hint`、`hard_constraints`、`publication_status` 和 `budget_remaining`：

- `scope`、attempt、refs、issues、focus 和 generation context 用来判断当前证据是否属于本次任务；focus 已应用不代表已经获得 observation。
- `review` 中的 `repair_kind` 和 `repair_hint` 解释审核为什么失败；只要没有 terminal、预算耗尽、授权越界、无效来源、非法 ChartSpec 或失败候选发布，模型可以在授权范围内自主选择观察、测量、修正 ChartSpec、恢复来源或停止。
- `hard_constraints` 只表示不能绕过的代码边界，例如当前候选不可发布或恢复已终止。不要通过改写 prompt、自由文本或旧事件来绕过这些边界。
- 补充 measurement 应沿用有效的 attachment、panel、attempt 和 refs；每个工具会独立校验范围、来源和结构。若没有足够 observation、范围不一致或预算耗尽，停止猜测并保持未发布。

如果 `state.measurement_evidence` 不为空，它是当前 run 中可供主 Agent 判断的紧凑测量结果列表。逐项读取 `measurement_ref`、`attachment_id`、`panel_id`、`tool`、`status`、`scope`、`observation_scope`、`effective_scope`、`evidence_refs`、`series_metadata`、warnings 和 issues。状态与质量是描述性信息，不是自动决策或调用工具的指令；根据图像与当前任务决定如何使用候选。确需补充时，主 Agent 可在同一 panel 主动再次调用测量工具并提供 `measurement_target`。

测量结果只是候选证据。可以直接使用当前 observation 的全部或部分 refs，通过 `assemble_spec.measurement_ref + evidence_refs` 表达实际采用的证据；也可以忽略不可靠候选、改用视觉或其他已授权证据、使用同一图表测量工具的 `measurement_target` 做有界补充，或停止。首次观察范围使用 `observation_scope`，不要求 parent attempt；补充 target 优先使用当前 refs 和 `include`/`exclude`，不得跨 attachment/panel/parent attempt，也不得重复已完成 target。局部结果必须重新读取；`focus_empty`、`focus_insufficient`、来源不一致或预算耗尽时停止猜测。生成审核失败会阻止当前候选发布，但不会把 `repair_kind` 升级为固定执行流程；任何修复产生的新候选仍必须重新审核。
