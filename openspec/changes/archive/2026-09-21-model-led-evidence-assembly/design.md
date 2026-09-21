## Context

当前链路已经具备 panel registry、图表测量工具、overlay、measurement session、共享 review coordinator、`assemble_spec` 校验和生成图审核。问题在于 measurement attempt 的质量状态同时被当作诊断结果和主流程授权：测量出现局部 warning 后，shared review gate 会阻塞其他观察，而 `assemble_spec` 又要求 attempt 为 `accepted`。详见 proposal.md；本设计只说明如何将现有能力重新组合。

当前工具坐标和来源约束必须继续保留：所有观察都绑定授权 attachment，面板工具只能在当前 panel 内运行，定向重测不能跨越父 attempt 或静默扩大搜索范围。

## Goals / Non-Goals

**Goals:**

- 让 VLM 在一次主链路中决定工具顺序、首次观察范围、候选取舍、系列语义映射和是否重测。
- 把 measurement observation、质量诊断和主 Agent evidence decision 分成独立状态。
- 允许同一 attempt 中存在被舍弃的误检候选，同时组装被选择的有效候选。
- 保持来源归属、范围、幂等、资源上限、ChartSpec 结构和生成图发布审核的硬约束。
- 让 test3 类场景可以在排除图例候选后直接组装，不因系列文字 warning 进入无穷重测。

**Non-Goals:**

- 不重新实现柱状图、折线图、饼图或 OCR 算法。
- 不在本 change 中引入 SAM、新的 OCR 引擎或新的模型 provider。
- 不取消生成图审核，也不允许未经审核的候选发布。
- 不把 VLM 的自然语言结论直接视为授权、范围或 ChartSpec 结构校验结果。

## Decisions

### 1. 用三类状态替代单一 measurement acceptance

保留现有 attempt/session/lineage 作为持久化和恢复身份，但将语义拆为：

```text
Observation execution: completed | failed
Quality diagnostics: warnings / issues / confidence / scope
Agent decision: pending | selected | discarded | abandoned
```

现有 `partial`、`remeasure_required` 和 `unsupported` 继续作为质量诊断兼容字段，不再直接决定主链路是否暂停。新的证据决策记录 attempt、selected refs、discarded refs、可选的 semantic mapping 和 evidence basis。

选择该方案是因为它保留历史数据兼容性，同时消除“工具质量状态”和“模型是否采用”的循环依赖。替代方案是完全删除 measurement session，但会丢失重连、幂等和评测所需的证据 lineage，因此不采用。

### 2. 区分首次 observation_scope 与后续 measurement_target

首次工具调用允许模型提交 `observation_scope`：

```text
panel_id + coordinate_space + include[] + exclude[] + objective[]
```

默认使用 `panel_norm` 坐标，服务端转换为源图和局部 crop 坐标；工具返回实际应用范围和 overlay。已有 attempt 的补充仍使用 `measurement_target`，可以引用 refs 或有界 bbox/polygon，并必须带父 attempt。

两者使用同一范围解析和边界校验，但生命周期不同：首次 scope 不要求已有 session，repair target 必须校验当前 session 和父 attempt。这样既支持模型一开始框选 plot，也不会削弱重测的 lineage 约束。

替代方案是扩展现有 `measurement_target` 同时承载两种语义，但会继续把首次观察误认为 repair，容易重新引入 `measurement_session_not_found` 和 parent mismatch，因此不采用。

### 3. measurement review 从共享阻塞门禁降级为可追踪观察

测量工具执行后继续生成 observation、quality、overlay 和 trace 事件，但不再向 shared `ReviewCoordinator` 创建阻塞主链路的 measurement review。主 Agent 可以继续调用 OCR、布局观察、其他测量或 `assemble_spec`。

真正的硬门禁移动到两个位置：

- 观察工具入口：attachment、panel、scope、父 attempt、重复 target 和资源边界。
- `assemble_spec` 入口：selected/discarded refs、来源、范围、引用存在性、必要数值和 ChartSpec 结构。

生成图审核仍使用 shared review gate，因为它保护的是最终 publish，而不是某个观察候选是否可以被模型查看。

替代方案是保留 measurement gate，只增加一个“接受 partial”动作。这仍会要求模型等待额外审核状态，并且无法自然表达“舍弃 B1/B4、采用其余候选”，所以不采用。

### 4. 组装使用候选级 evidence decision

`assemble_spec` 接受当前 attempt 的显式 decision：

```json
{
  "attempt_id": "matt_xxx",
  "selected_refs": ["B2", "B3"],
  "discarded_refs": ["B1"],
  "series_map": {"S1": "Target"},
  "evidence_basis": "measurement_plus_visual"
}
```

校验顺序为：

1. 校验 decision 所属 session、attachment、panel 和当前 attempt。
2. 校验 refs 存在、selected/discarded 不重叠且未越界。
3. 对 selected refs 检查被使用字段的必要数值；空值候选不能被当成确定数值使用。
4. 构建 ChartSpec 并执行已有结构校验。
5. 将 decision、质量 warning 和来源信息写入 provenance。

未被选择的候选不参与第 3 步，因此一个 attempt 中的图例误检不会拖累真实柱体。模型可以不提供 measurement provenance，明确放弃 observation 后走直接视觉组装，但 trace 必须保留 abandoned 记录。

### 5. 主 Agent 提示词采用“观察—选择—装配”契约

静态层明确模型负责证据规划和候选判断；动态工具层提供 `observation_scope` 与 `measurement_target`；过程层提供原始 JSON、overlay、refs 和 warnings；Run/Turn 层只提供当前 panel、预算、生成审核状态和可执行动作。

提示词必须明确：warning 不自动等于重测；模型需要先查看 overlay 再选择或舍弃；`series_1`、`B1` 等只用于交叉定位；无法确认的字段应保持不确定或放弃，不得猜测。

### 6. 使用事件兼容层保留前端和评测可追溯性

新增或复用以下有界事件语义：

- `measurement_observed`：工具完成，携带 scope、attempt、refs、quality 摘要。
- `measurement_evidence_selected`：模型提交 selected/discarded 和语义映射。
- `measurement_repair_required/rejected/exhausted`：仅表示模型主动发起的局部补充生命周期。
- `chart_review_*`：继续表示生成候选审核。

旧客户端可以继续读取旧的 measurement repair 字段；新客户端根据 `blocking` 和 review type 区分“证据 warning”与“发布审核阻塞”。事件不能包含原始图片、绝对路径、密钥或 provider 原始 payload。

### 7. 保持生成审核作为最后一道发布保护

测量和语义组装完成后，render 产生 candidate；生成图 VLM 审核继续检查源图、ChartSpec 和生成图的一致性。审核失败时只允许对该 candidate 做有限修复和重渲染；审核未通过或预算耗尽时不得发布。

## Risks / Trade-offs

- **模型误删真实候选** → overlay、ref、selected/discarded 事件必须可见；必要字段的空值和非法 ref仍由代码拒绝；真实图表评测增加“误删/漏删”断言。
- **模型选择带 warning 的候选** → warning 保留在 provenance 和前端；仅对被使用字段的空值、越界和来源错误做硬拒绝；最终生成图仍需 VLM 审核。
- **首次 scope 过窄导致漏检** → 工具返回 `focus_empty/focus_insufficient` 和实际范围；模型可以显式扩大一次 scope，但工具不得静默放大。
- **直接视觉组装削弱测量溯源** → 组装结果必须标记 `evidence_basis`；abandoned observation 保留 lineage，前端不得显示成已采用测量。
- **旧事件和旧客户端不兼容** → 新事件采用 additive 字段和稳定英文类型；历史记录继续保留旧 projection，前端提供未知事件安全回退。
- **模型在 warning 下循环调用工具** → 保留全局 step/tool budget、target fingerprint 幂等和 prompt 中的停止条件；预算耗尽明确归因于 measurement repair，不得伪装成 generated review。
- **多 panel 证据串用** → 所有 decision 和 scope 都必须校验 attachment、panel、attempt；selected refs 不满足 lineage 时组装直接失败。

## Migration Plan

1. 先增加 observation scope、evidence decision、事件字段和向后兼容的状态读取，不改变旧记录的解析。
2. 将 `assemble_spec` 的验证从 attempt acceptance 改为 selected refs 验证，同时继续写出旧 measurement quality 字段供历史 UI 使用。
3. 停止 measurement review 创建共享 blocking gate，保留 observation/repair 事件；生成图 review gate 保持原有行为。
4. 更新主 Agent prompt 和前端映射，完成 test3 及基础图表评测。
5. 验证 checkpoint/reconnect、旧 run 回放和旧客户端 fallback 后，再删除仅服务于旧 measurement blocking loop 的兼容分支。

回滚时可以恢复旧的 measurement gate 读取逻辑；新的 observation 和 decision 记录仍可被旧 projection 忽略，不破坏历史 run。实现过程中不得删除旧 session/attempt 数据。

## Open Questions

无。坐标格式、候选决策、门禁边界和生成审核归属已经在本设计与 delta specs 中确定。
