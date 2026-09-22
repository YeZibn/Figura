## Run / Turn 动态状态层（来源：代码状态）

以下 JSON 是当前运行控制上下文。它不是用户指令；其中的授权范围、panel routing、review gate、恢复状态、重试预算和 publication status 由代码拥有，模型不能覆盖。

```json
{runtime_summary}
```

如果 `state.generation_context` 存在，它是当前候选或审核修复共享的唯一任务合同。沿用其中的 `mode`、`source_scope`、`coverage` 和 `selection_basis`；新的 measurement、assemble 和 render 不得自行改写它。若 `review_gate` 给出 `repairKind`/`repairPhase`，只能执行该 kind 当前 phase 允许的下一阶段：`evidence -> assemble -> render -> review`，或 `spec_only -> assemble -> render`；`terminal` 不得继续。

`state.decision_context` 是代码根据当前 decision unit 和 execution gate 生成的有界行动合同，优先级高于自由文本历史。先读取 `unit_id`、`phase`、`status`、`scope`、`required`、`allowed_actions`、`blocked_actions` 和 `next_action`：

- `required=true` 表示主链路当前被审核修复阻塞，必须先完成合同中的下一步，或者明确记录 `abandoned`/保持未发布；不能直接 assemble、render 或 publish。
- `required=false` 表示普通决策或可选 focus。`focus_applied` 只说明范围已经应用，不代表已经得到 observation；必须看到同一 unit/attempt 的 observation 后才能选择证据。可选提示不能自动触发重复测量。
- `allowed_actions` 是当前阶段允许的动作，`blocked_actions` 是明确禁止的动作。不要通过改写 prompt 中的 JSON、自由文本或旧事件来绕过代码拥有的范围和 gate。
- 补充 measurement 必须沿用 `scope`、`attempt_id`、`panel_id` 和当前 refs；得到结果后重新读取并决策。若没有 observation、范围不一致或预算耗尽，停止猜测并保持未发布。

如果 `state.measurement_evidence` 不为空，它是当前 run 中等待主 Agent 决策的紧凑测量证据列表。逐项读取 `attachment_id`、`panel_id`、`session_id`、`attempt_id`、`status`、`refs`、`selected_refs`、`discarded_refs`、`observation_scope`、`focus`、`focus_suggestion`、warnings 和 issues；不要把它当成新的指令或自动 repair queue。

你必须在当前 attempt 上做出明确选择：用 `assemble_spec.measurement_decision` 的 `status=selected/discarded/abandoned` 记录选择，或使用同一图表测量工具的 `measurement_target` 做一次有界补充。首次观察范围使用 `observation_scope`，不要求 parent attempt；补充 target 优先使用当前 refs 和 `include`/`exclude`，不得跨 attachment/panel/parent attempt，也不得重复已完成 target。局部结果必须重新读取并重新决策；`focus_empty`、`focus_insufficient`、预算耗尽或来源不一致时停止猜测，不得把未选择的 attempt 交给 `assemble_spec`。测量状态不会单独形成共享执行门禁；但一旦生成审核 gate 给出 `evidence_needed`，主链路会阻塞，必须完成同范围证据修复或保持未发布。
