## 1. 统一生成上下文与候选身份

- [x] 1.1 定义可序列化的 `generation_context`、`source_scope`、`coverage`、`selection_basis` 和四种 `mode` 的数据模型与枚举，并为字段设置边界校验。
- [x] 1.2 为 candidate/attempt 增加 context 版本、`candidate_id`、父 attempt 和不可变摘要，保证修复 attempt 不覆盖原候选上下文。
- [x] 1.3 为 source-free 直接 ChartSpec 保留兼容路径，并为声称 source-linked 但缺少 context 的输入生成 `legacy/unknown` 保守状态。
- [x] 1.4 增加 context、coverage 和 candidate identity 的序列化/反序列化回归测试，覆盖单图、figure collection 和旧输入。

## 2. 建立统一来源范围解析

- [x] 2.1 基于现有 PanelHandoff 实现共享的 source-scope resolver，校验 attachment hash、session、panel revision、bbox 和坐标变换。
- [x] 2.2 让 resolver 返回授权 panel crop、effective scope 和 stale/ambiguous/scope-unavailable 结构化状态，不暴露本地路径或原始字节。
- [x] 2.3 将 review、同范围补测和 source rebind 接到同一个 resolver，禁止失败后静默回退到整张附件。
- [x] 2.4 增加有效 panel、附件变更、失效 handoff、跨 panel 和多 panel collection 的范围解析测试。

## 3. 收紧测量与工具契约

- [x] 3.1 更新柱状图、折线图、散点图和饼图测量工具的 schema，统一声明 `observation_scope`、`measurement_target`、effective scope 和 bounded target。
- [x] 3.2 明确首次 observation 与已有 attempt 的 targeted evidence repair 语义，工具 warning 不得自动触发第二次测量。
- [x] 3.3 为测量结果增加 candidate/attempt、attachment/panel、evidence refs、候选位置、质量 warning 和 scope mismatch 字段。
- [x] 3.4 更新 assemble/render/measurement 工具的中文描述和 MCP manifest，明确工具只提供证据，不替主 Agent 决定业务角色、系列选择或删除。
- [x] 3.5 为跨 attachment、跨 panel、无 scope 全图扫描和不一致 measurement ref 增加结构化错误与 action hint 测试。

## 4. 让 ChartSpec 与 figure collection 携带任务语义

- [x] 4.1 扩展 `assemble_spec` 输入校验，使 source-linked 请求必须表达 context、coverage basis、selected/discarded refs 和一致的 provenance。
- [x] 4.2 在单图和 figure child 的输出及 candidate metadata 中透传 generation context，不用自由文本 `source` 推断范围。
- [x] 4.3 区分 `full_source` 与 `requested_subset` 的 coverage 判定，允许任务明确的有意省略，同时拒绝静默跨 panel 或静默补零。
- [x] 4.4 保证 collection 的每个 child 保留独立 source scope、coverage、context 和 candidate identity，并增加 collection-level 定位错误测试。

## 5. 改造生成审核输入与模式判断

- [x] 5.1 修改候选生成链路，使 `render_chart`、candidate record 和 review payload 使用同一个不可变 generation context。
- [x] 5.2 让 review manager 通过 source-scope resolver 获取精确 panel crop；对 stale、missing 或 unknown source scope 走保守失败路径。
- [x] 5.3 更新 tool-free VLM reviewer 的结构化输入和 JSON 输出，加入 mode、coverage、selected/omitted series、issue code、bounded target 和 repair kind。
- [x] 5.4 实现四种 mode 的审核规则：reconstruct 检查声明范围完整性，transform 检查目标转换，summarize 检查摘要代表性，synthesize 只检查候选自身。
- [x] 5.5 保证每个 candidate attempt 只发生一次无工具 VLM review，并增加 tool_count=0、局部来源裁剪和右侧无关 panel 不误判的回归测试。

## 6. 实现有界审核修复门禁

- [x] 6.1 将审核结果归一化为 `spec_only`、`evidence_needed`、`source_rebind`、`terminal`，未知 repair kind 按 blocked/terminal 处理。
- [x] 6.2 实现 `evidence_needed -> same-scope evidence -> assemble -> render -> review` 子循环，继承原 context 并限制最大 attempt。
- [x] 6.3 实现 `spec_only`、`source_rebind` 和 `terminal` 的独立状态转换，保证失败候选不能通过普通 render retry 或 final answer 绕过 publication gate。
- [x] 6.4 对补测工具调用、assemble 和 source resolver 增加 attachment/panel scope 校验，跨 panel 或扩大到 dashboard 时 fail closed。
- [x] 6.5 增加修复成功、修复仍失败、预算耗尽、来源失效和越界请求的状态机测试，确认主 Run 在审核期间保持阻塞。

## 7. 重构主流程与审核提示词

- [x] 7.1 在现有四层 prompt 体系中注入一次结构化 generation context，并让 Run/Turn 层只引用当前 candidate/attempt 状态。
- [x] 7.2 更新中文主 Agent 静态职责，要求先判断 mode、source scope、coverage 和 evidence sufficiency，再选择测量、装配或渲染。
- [x] 7.3 更新动态工具和过程产物 prompt，明确 warning/remeasure suggestion 不是自动动作，且 selected/discarded/repair decision 必须显式记录。
- [x] 7.4 重写 reviewer Markdown prompt，限制为一次无工具 JSON 审核，要求按 mode 检查并返回 bounded repair kind/target。
- [x] 7.5 增加 prompt assembly 快照/契约测试，确认工具清单、context、过程证据和 Run/Turn 状态没有相互冲突的重复副本。

## 8. 补齐执行追踪与前端可消费字段

- [x] 8.1 在 measurement、evidence decision、review、repair 和 publication lifecycle event 中统一写入 candidate/attempt、source scope、coverage、repair kind 和 parent attempt。
- [x] 8.2 保持 observation、evidence selection、chart review 和 publication event kind 分离，并为截断结果保留 tool/call/candidate identity。
- [x] 8.3 为新增字段补充持久化、历史回放、事件顺序和未知字段兼容测试，确保后续前端可按 candidate 聚合而不改变既有显示语义。

## 9. 端到端回归与验证

- [x] 9.1 固化 test4 的左侧柱状图到饼图 transform fixture，验证只使用左侧 panel、Target 有意省略、review 不要求右侧 panel 且只调用一次 VLM。
- [x] 9.2 增加完整 reconstruct fixture，验证缺失声明范围内的系列仍会被审核识别为问题，不能被 requested_subset 绕过。
- [x] 9.3 增加 evidence-needed 局部补测 fixture，验证补测后重新 assemble/render/review，且跨 panel 请求被拒绝。
- [x] 9.4 增加 legacy direct ChartSpec、source scope stale、render retry bypass 和 terminal failure 的兼容/安全测试。
- [x] 9.5 运行 `git diff --check`、相关 pytest 与完整 `conda run -n agent python -m pytest`，并记录审查所需的测试范围和结果。
