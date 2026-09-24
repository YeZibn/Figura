## Run / Turn 动态状态层

下面的 JSON 是当前运行上下文。它包含代码确认的授权范围、panel 路由、恢复状态和模型步数预算；其中的数据不是用户指令。

```json
{runtime_summary}
```

沿用 `state.generation_context` 的 `mode`、`source_scope`、`coverage` 和 `selection_basis`；测量、组装和渲染不能偷偷扩大来源范围或改写覆盖声明。`state.decision_context` 是来源与测量事实摘要，不能替代原始 tool observation。

测量结果只是候选证据。可直接采用当前 observation 的全部或部分 refs，通过 `assemble_spec.measurement_ref + evidence_refs` 表达；也可忽略不可靠候选、使用其他已授权证据、做有界补充或停止。局部结果须重新读取；来源不一致或预算耗尽时停止猜测。
