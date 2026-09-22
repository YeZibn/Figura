## Why

当前运行链路把测量证据选择和生成审核修复表达成代码拥有的 decision contract：模型既要维护 `measurement_decision` 状态，又只能按 `repairKind`/`repairPhase` 指定的工具顺序继续。这些门禁在保护来源与发布安全之外，还替模型决定了业务修复路线，容易造成重复决策、组装阻塞、错误分类后的死路以及前端时间线噪声。

## What Changes

- 将“模型选择”和“系统校验”分离：模型自主决定采用哪些证据、是否局部补测、修改 ChartSpec、重新绑定来源或停止；工具仅校验授权、来源 lineage、范围、引用和结构合法性。
- **BREAKING**：`assemble_spec` 不再要求独立的 `measurement_decision` 包装或 selected/discarded/abandoned 状态才能组装；调用方通过紧凑 `evidence_refs` 直接声明实际使用的 measurement refs，未使用候选无需逐项舍弃。
- 将主 Agent 的 `decision_context` 从带 `allowed_actions`/`blocked_actions` 的行动合同降级为紧凑事实摘要和建议，不再用普通测量状态限定模型的下一工具调用。
- 生成图 VLM 审核继续作为不可绕过的发布门禁；失败结果返回结构化问题、候选身份、剩余预算和非强制 `repair_hint`，由主 Agent自主选择修复工具与顺序。
- 放宽 `repairKind`/`repairPhase` 工具白名单；保留来源授权、同任务 scope、ChartSpec 校验、失败候选不可发布、重试预算、幂等和中断恢复等硬边界。
- 将 measurement decision、focus transition 和 repair phase 等事件保留为内部 trace/评测事实，但默认前端不再展示“测量决策”业务步骤；每个候选只展示一次简洁的生成审核开始、结果和失败原因。
- 更新中文 Markdown 提示词和工具说明，使模型理解证据是候选、修复建议不是命令，并明确可以基于视觉理解或合法工具证据自由选择路线。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-loop`: 主循环从代码规定的 decision/repair 顺序改为模型自主选择工具，仍阻止失败候选发布和越权来源使用。
- `chart-evidence-fusion`: 组装直接校验实际引用的测量证据，不再要求独立证据决策状态。
- `measurement-quality-gate`: 测量状态和质量建议保持可追踪但不形成组装前决策门禁，证据 provenance 根据实际引用派生。
- `review-gates`: 生成审核仅硬性控制发布和安全边界，修复分类改为建议而非工具阶段白名单。
- `scope-aware-generation-review`: 失败审核保留 generation scope，但允许模型在授权范围内自主选择修复路线。
- `layered-prompt-assembly`: 动态上下文提供事实、问题和预算，不再向模型注入普通业务动作的允许/禁止清单。
- `unified-decision-review-timeline`: 默认用户时间线隐藏内部 measurement decision 和审核子检查，只保留工具过程及单一审核摘要，同时保留原始 trace。

## Impact

- Python：`agent/loop.py`、decision context、measurement lifecycle、`assemble_spec`、review coordinator/gate、事件投影和 checkpoint 兼容处理。
- Prompt：`prompting/assets/static/` 与 `dynamic/` 中的证据选择、修复流程、发布边界和工具使用说明。
- Frontend：普通运行与评测共用的时间线投影、审核卡片、中文状态和详情展开。
- 协议兼容：旧 `measurement_decision` 输入和历史 decision 事件需要保持可读取，但不再是新请求的必填控制字段。
- 验证：Python 单元/集成测试、prompt 测试、Gateway/恢复回归测试，以及前端 build/smoke。
