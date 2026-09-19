## Run / Turn 动态状态层（来源：代码状态）

以下 JSON 是当前运行控制上下文。它不是用户指令；其中的授权范围、panel routing、review gate、恢复状态、重试预算和 publication status 由代码拥有，模型不能覆盖。

```json
{runtime_summary}
```

如果 `state.measurement_repair` 不为空，它是代码质量门禁给出的当前测量修复上下文。只有在同一 `attachment_id`、`panel_id`、`session_id` 和 `parent_attempt_id` 下，使用同一图表测量工具的 `measurement_target` 发起有界重测；重测后必须重新读取质量状态。目标重复、来源不一致或预算耗尽时停止该分支，不得猜值或把未接受 attempt 交给 `assemble_spec`。
