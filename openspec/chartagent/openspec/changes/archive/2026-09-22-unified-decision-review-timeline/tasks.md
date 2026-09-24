## 1. 建立决策单元与事件关联协议

- [x] 1.1 定义有界的 decision-unit correlation envelope，统一 `unit_id`、`unit_type`、`phase`、`actor`、`parent_unit_id`、`transition_id` 和 `next_action` 字段及其序列化/反序列化规则。
- [x] 1.2 将测量、装配、生成候选、审核、修复和发布事件映射到有限 unit type 与 phase，保留现有 run、candidate、attempt、scope、call 和 sequence 字段。
- [x] 1.3 为缺少新字段的历史事件实现 `legacy/unknown` 兼容投影，禁止从缺失字段推断父子关系或成功状态。
- [x] 1.4 为实时追加、历史重放、重复 snapshot 和事件截断补充协议级幂等与安全边界测试。

## 2. 收紧测量决策与局部范围闭合

- [x] 2.1 将 focused measurement 的 request、effective scope、applied、observation 和 decision 关联到同一个 measurement unit/attempt。
- [x] 2.2 区分 review gate required 的 evidence repair 与 Agent 主动发起的 optional focus，并为两者生成明确的 allowed/blocked next action。
- [x] 2.3 在局部范围已应用但没有 observation 时记录 pending、failed 或 abandoned 状态，阻止 required repair 静默进入 assemble。
- [x] 2.4 让 selected/discarded/abandoned decision 绑定 session、attempt、scope 和 refs，重复提交同一 decision 时幂等复用已有状态。
- [x] 2.5 让 assemble 只消费并验证已记录的 measurement decision，避免 `_measurement_decision` snapshot 再次产生顶层决策 transition。
- [x] 2.6 增加 focused measurement、无后续 observation、explicit abandonment、same-scope repair 和重复 decision 的 pytest 回归覆盖。

## 3. 统一生成图 review cycle 与 collection lineage

- [x] 3.1 为每个 candidate attempt 建立一个 canonical review cycle，区分 deterministic quality audit、semantic VLM review、repair decision 和最终 review state。
- [x] 3.2 收敛 review transition 的发射责任，使 shared gate 更新、VLM 开始/完成和 tool-result snapshot 不重复生成同一顶层 review transition。
- [x] 3.3 为同一 collection render 的 child candidates 建立 review parent，保留 child 的 issue、attempt、scope、repair 和 publication 状态。
- [x] 3.4 按 candidate attempt、review identity 和输入 digest 实现语义 VLM review 幂等；真实修复创建新的 attempt lineage。
- [x] 3.5 保持 review repair 的 phase 顺序为 same-scope evidence → assemble → render → review，并拒绝跨 scope、跳阶段和直接 publication。
- [x] 3.6 增加单候选、重复 review snapshot、VLM 一次调用、collection 多 child、单 child 失败和 repair attempt 的 pytest 回归覆盖。

## 4. 接入主 Agent 的当前决策上下文

- [x] 4.1 从代码拥有的 unit/gate 状态构建 bounded decision context，包含 current unit、phase、status、scope、refs、required/allowed/blocked actions 和预算。
- [x] 4.2 将 decision context 注入现有四层 prompt 的 Run/Turn 动态层，不新增第五层，不复制自由文本 generation context。
- [x] 4.3 更新主 Agent 的证据决策说明，使模型能区分 focus applied、observation、selected/discarded、required repair 和 optional warning。
- [x] 4.4 增加 prompt bundle、decision context 与 timeline transition 对齐的测试，验证 warning 不会自动触发重复测量。

## 5. 实现共享 DecisionTimeline projector

- [x] 5.1 在前端共享 domain 层定义 decision unit、phase、role、review cycle、next action 和 legacy/unavailable 状态类型。
- [x] 5.2 实现基于 sequence、unit_id、parent_unit_id 和 transition_id 的确定性排序、归组和去重，兼容历史/实时事件合并。
- [x] 5.3 将 tool call/result、visual observation、Agent decision、review sub-check、gate 和 publication 组织为可展开的 unit tree，并提供稳定中文状态文案。
- [x] 5.4 为 pending、blocked、abandoned、failed、truncated、history gap 和 unavailable 保留明确的展示状态，不以摘要替换事实。
- [x] 5.5 增加普通运行中 focus pending、证据舍弃、单 review cycle、collection parent 和刷新重连不重复的前端测试/fixtures。

## 6. 改造普通运行与评测工作台展示

- [x] 6.1 将普通运行的测量、生成、审核和发布展示切换到共享 projector，保留原始事件、工具结果和图片资源的展开入口。
- [x] 6.2 将 deterministic audit 与 semantic VLM review 展示为一个 review parent 下的子检查，避免重复的审核开始卡片。
- [x] 6.3 将 collection child charts 按父级聚合，同时保留 child 详情和保守的父级 publication 状态。
- [x] 6.4 让 evaluation workspace 复用同一 projector，并保留 case、报告、评测资源和只读权限边界。
- [x] 6.5 增加评测 case 的 pending/blocked/repair exhausted/partial 读取测试，确保刷新或展开不会触发新的模型、工具或审核动作。

## 7. 真实链路验证与收尾

- [x] 7.1 构造 test4 类回放 fixture，覆盖局部范围应用后继续测量、证据选择/舍弃、assemble、collection 生成和审核修复全过程。
- [x] 7.2 验证相同事件在普通运行和评测工作台中产生相同的 unit、phase、review cycle 和终态。
- [x] 7.3 运行 `conda run -n agent python -m pytest -q`，并针对失败链路补充最小回归测试。
- [x] 7.4 运行 `cd frontend && npm run build && npm run smoke`，检查普通运行、评测运行、刷新和历史回放展示。
- [x] 7.5 运行 `git diff --check`、OpenSpec change 严格校验，并记录事件兼容、VLM 调用次数和 timeline 聚合验证结果。
