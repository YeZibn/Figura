## Why

当前图表链路把测量质量、证据选择和主流程门禁绑定在同一个 attempt 状态上。`test3` 已经证明：模型能够通过 overlay 识别并舍弃误检候选，但只要测量结果仍是 `partial`，`assemble_spec` 就会被拒绝；而释放测量审核又依赖组装成功，最终形成循环阻塞。需要把模型的主观判断能力真正纳入链路，同时保留来源、范围和结构安全边界。

## What Changes

- **BREAKING** 将测量结果从“必须整体 accepted 才能继续”改为“模型选择候选证据后按候选校验”；普通 warning、未解析系列标签和可舍弃候选不再阻塞主流程。
- 新增首次观察使用的 `observation_scope`，允许 VLM 在第一次 OCR/CV 调用前指定 panel 内的 plot、legend、axis 等 include/exclude 范围；`measurement_target` 继续只负责已有观察后的局部补充。
- **BREAKING** 取消 measurement review 对 OCR、布局观察、其他测量和证据组装的独占阻塞；测量质量审核保留为可追踪诊断，不再作为共享执行门禁。
- 将 `selected_refs`、`discarded_refs`、系列语义映射和放弃某次 observation 的决定纳入主 Agent 的组装输入，并保留完整 attempt lineage。
- 保留 attachment/panel 授权、范围、引用、幂等、ChartSpec 结构和资源预算等硬校验；生成图审核继续作为 render 后的发布门禁。
- 更新主 Agent 的分层提示词、运行事件和前端展示，使“观察、警告、选择、舍弃、重测、组装、生成审核”成为清晰的过程状态。
- 增加针对多面板柱状图、首次范围标定、图例误检、局部重测、放弃测量证据和生成审核失败的回归评测。

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `measurement-quality-gate`: 将 attempt 级接受门禁改为候选证据选择与硬性来源校验。
- `chart-evidence-fusion`: 明确 VLM 负责证据融合、候选取舍和语义映射，测量 warning 不再强制重测。
- `review-gates`: measurement review 改为非阻塞诊断；生成图审核继续阻塞发布。
- `tool-system`: 增加首次 `observation_scope`，并统一范围、坐标和局部补充契约。
- `chart-layout-context`: 支持模型提供并复用 panel 内的 plot、legend、axis 观察范围。
- `agent-loop`: 移除测量审核独占子循环，允许主 Agent 自主组合观察、选择、舍弃和组装。
- `layered-prompt-assembly`: 更新静态职责、动态工具说明、证据结果和 run/turn 状态层。
- `execution-trace`: 记录 observation scope、候选选择、舍弃、放弃和非阻塞 warning，区分测量观察与生成审核。
- `desktop-client`: 展示候选证据及其选择过程，不再把普通测量 warning 显示为主流程阻塞。

## Impact

- 主要影响 `src/chartagent/measurement.py`、`agent/loop.py`、`tools/chart/specification.py`、`tools/chart/observation/scope.py`、`review/` 和提示词资源。
- 需要调整测量工具参数与 assemble 输入的模型可见契约，并同步更新 Python 单元测试、真实图表评测和 React 前端事件映射。
- 不新增外部服务或模型依赖；继续使用当前 `agent` Conda 环境及现有 OCR/CV/VLM 能力。
- 旧的“测量 attempt 必须 accepted 才能组装”行为将不再兼容，但 attachment、panel、引用归属和最终发布审核仍保持严格校验。
