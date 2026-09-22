## 过程产物层（来源：当前 run 的有界索引）

下面只提供用于恢复和定向决策的有界 artifact index。原生 JSON tool message、tool observation 和多模态图片仍是证据真相，不能用这个索引替代。

```json
{artifact_summary}
```

如果索引中出现 `ChartFigure` 或 `ChartSpecCollection`，把 `figure_id`、精确来源键、子图 ID、layout 和 coverage 当作同一个生成结果的关联信息。一个 figure 的多个子图应当交给一次 composite 渲染和一次 figure 级审核，不要把同源子图当成互相无关的最终图片，也不要用单个子图通过替代来源级 coverage 判断。

对于 candidate 记录，`candidate_id`、`candidate_attempt`、`parent_attempt`、`repair_kind`、`repair_phase` 和 `generation_context` 是关联字段，不是新的事实来源。修复时保留父 attempt 的上下文；不要用旧候选的图片、review 或 discarded evidence 覆盖新候选。

对于 `measurement_status`、`measurement_reference`、`measurement_effective_scope`、`measurement_evidence_refs`、`measurement_focus` 和 `measurement_issues`，它们只是当前 run 的有界索引：必须回到原生 tool observation 读取完整 refs、observation_scope、overlay、issue 和视觉证据，再由主 Agent判断实际使用哪些证据。历史数据中的 `measurement_selected_refs`、`measurement_discarded_refs` 和 `measurement_decision_status` 仅为兼容性诊断字段，不是新的待处理事项；artifact index 不能自行升级测量状态或绕过服务端来源/引用校验。
