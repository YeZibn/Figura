## 1. 证据状态与范围契约

- [x] 1.1 定义并实现 `observation_scope` 的统一结构，支持 `panel_norm`/源坐标、include/exclude 区域、区域角色和分析目标。
- [x] 1.2 将首次 `observation_scope` 与已有 attempt 的 `measurement_target` 分离，保证首次观察不要求 session/parent attempt，定向重测仍校验 lineage。
- [x] 1.3 拆分 measurement execution、quality diagnostics 和 Agent evidence decision 的内部投影，保留旧状态字段用于历史记录与兼容读取。
- [x] 1.4 实现 selected/discarded/abandoned decision 的有界序列化、恢复和幂等校验。

## 2. 图表工具与范围应用

- [x] 2.1 更新柱状图、折线图、散点图和饼图工具 schema，使首次调用可接收 `observation_scope`，已有调用继续接收 `measurement_target`。
- [x] 2.2 在统一 scope resolver 中完成 panel 范围校验、归一化坐标转换、源图/局部 crop 映射和越界错误返回。
- [x] 2.3 确保初次 scope 和 focused target 都返回 requested/applied 状态、实际搜索区域、坐标信息和 overlay。
- [x] 2.4 保证 focus_empty/focus_insufficient 不会静默扩大为全 panel 或全源图测量，并为重复 target 保留幂等结果。
- [x] 2.5 保证工具候选 refs、内部系列身份、人类标签和 warning 独立输出，空值候选不会被伪造成可用数值。

## 3. 主 Agent 循环与审核协作

- [x] 3.1 移除 measurement observation 对 shared ReviewCoordinator 的独占 blocking gate，允许 OCR、布局观察、其他测量和候选组装继续由模型决定。
- [x] 3.2 调整 Agent loop，使模型可以在第一次测量前提供 scope，并在观察后主动选择、舍弃、补充或放弃证据。
- [x] 3.3 将局部重测限制为显式的主 Agent tool call，保留 parent attempt、target fingerprint、预算和拒绝原因。
- [x] 3.4 区分 measurement repair exhaustion 与 generated chart review exhaustion，避免将测量分支耗尽映射为生成审核失败。
- [x] 3.5 保留生成图 review gate 的阻塞行为，只允许关联 candidate 的修正和重新渲染通过审核后发布。

## 4. assemble_spec 与 provenance

- [x] 4.1 将 `assemble_spec` 的 measurement gate 改为 selected/discarded refs 的来源、范围、存在性、非重叠和必要字段校验。
- [x] 4.2 允许同一 attempt 中舍弃误检候选后组装有效候选，不因 attempt 级 warning 或未解析系列标签整体失败。
- [x] 4.3 支持 `series_map`、`evidence_basis` 和 abandoned observation 记录，并将决策与 ChartSpec provenance 关联。
- [x] 4.4 保持无 measurement provenance 的直接视觉组装兼容，同时继续执行 ChartSpec 结构校验和后续生成审核。
- [x] 4.5 为非法 ref、空值 selected ref、跨 panel 引用和过期 attempt 返回定位明确的结构化错误。

## 5. Prompt 与运行上下文

- [x] 5.1 更新中文静态职责提示词，明确 VLM 负责证据规划、候选取舍、语义映射和停止/放弃判断。
- [x] 5.2 更新动态工具提示词，说明 `observation_scope` 与 `measurement_target` 的区别、坐标格式和适用时机。
- [x] 5.3 更新过程产物层，向模型提供原始 observation JSON、overlay、refs、warnings、selected/discarded 和 lineage，而不是只提供审核摘要。
- [x] 5.4 更新 run/turn 动态状态，移除“measurement review 必须优先修复”的强制动作，保留预算、来源和生成审核状态。
- [x] 5.5 增加停止规则：warning 不自动重测、同一 target 不重复、关键字段无法确认时保留不确定或放弃，不得猜值。

## 6. Trace、Gateway 与前端

- [x] 6.1 增加或复用 `measurement_observed`、`measurement_evidence_selected`、`measurement_evidence_discarded` 和 repair exhaustion 事件，并保持 run/sequence 幂等。
- [x] 6.2 更新 Gateway 的终态和错误分类，使 measurement repair exhaustion、assembly validation failure 和 generated review failure 可区分。
- [x] 6.3 更新前端运行时间线，展示 scope、overlay、候选 refs、selected/discarded、warning 和 attempt lineage。
- [x] 6.4 将普通 measurement warning 显示为非阻塞证据状态，将生成图审核继续显示为发布阻塞状态。
- [x] 6.5 为新增事件和旧事件提供稳定的简体中文映射、历史回放、重连去重和未知事件 fallback。

## 7. 测试与真实链路验证

- [x] 7.1 增加 scope resolver、坐标映射、越界、polygon/bbox、focused no-widen 和 target 幂等的 Python 单元测试。
- [x] 7.2 更新 measurement quality/session 测试，覆盖 warning 非阻塞、候选级选择、abandoned observation 和恢复状态保持。
- [x] 7.3 更新 Agent loop 测试，覆盖测量后继续 OCR/布局观察、首次 scope、主动重测、重测耗尽和生成审核独立阻塞。
- [x] 7.4 更新 assemble_spec 测试，覆盖舍弃图例误检后成功组装、非法 selected ref 拒绝、系列语义映射和直接视觉兼容。
- [x] 7.5 更新 trace/Gateway/前端测试，验证事件顺序、终态分类、历史回放、重连和完整过程展示。
- [x] 7.6 使用 `bar_line_dashboard` 重跑 test3，确认左侧柱状图能够排除图例候选后完成 assemble、render 和生成图审核，不发生重复全量测量。
- [x] 7.7 运行 Python 测试、`git diff --check`、前端 `npm run build` 和 `npm run smoke`，记录本 change 的验证结果。

验证记录：第二次 `bar_line_dashboard` 真实链路评测使用 `deepseek/deepseek-flash`，两个测量工具各调用一次，生成两个 figure 候选并全部通过审核发布。评测保留了一次可恢复的首次组装参数错误，后续由模型修正；该记录用于诊断，不影响最终运行完成。
