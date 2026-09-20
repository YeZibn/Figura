## 1. 建立共享审核契约

- [x] 1.1 定义有界的 ReviewRecord、ReviewDecision、ReviewIssue、RepairAction、EvidenceRef 和 ExecutionGate 数据模型及序列化规则
- [x] 1.2 实现审核状态迁移、attempt/lineage、预算校验和 subject/ChartSpec digest 匹配校验
- [x] 1.3 实现审核提交与结果应用的幂等身份、原子转换和旧审核事件归一化
- [x] 1.4 为共享审核模型和状态迁移补充单元测试，覆盖重复提交、过期结果和非法迁移

## 2. 接入测量审核硬门禁

- [x] 2.1 将现有测量质量审计包装为 MeasurementReviewAdapter，并为每个测量 attempt 生成统一审核记录
- [x] 2.2 在 Agent loop 的每个测量工具结果边界应用 ExecutionGate，阻止未接受测量进入 assemble 或后续生成
- [x] 2.3 在同一模型工具批次中截断审核阻塞之后尚未开始的调用，并将其记录为 not_started
- [x] 2.4 将定向重测限制为同一 attachment、panel、父 attempt 和 repair target，并在新 attempt 后重新审核
- [x] 2.5 补充测量审核失败、定向重测通过、重复 target、预算耗尽和批次截断测试

## 3. 接入生成图审核硬门禁

- [x] 3.1 将 ChartReviewManager 的候选审核结果映射到共享 ReviewRecord 和 ExecutionGate
- [x] 3.2 保证候选处于审核中或失败时不可发布、不可作为成功结果返回，且 pass_with_warning 只按策略显式放行
- [x] 3.3 将可修复 VLM 诊断转换为受控 ChartSpec 修复动作，并为每次修复创建新的 candidate lineage
- [x] 3.4 为审核超时、非法 VLM JSON、源证据缺失和 retry exhausted 建立明确的非发布终态
- [x] 3.5 补充候选审核阻塞、修复重绘、重复审核和禁止旧候选发布的集成测试

## 4. 接入运行记录与恢复

- [x] 4.1 扩展运行事件、运行摘要和 checkpoint，保存活动 ExecutionGate、审核引用、预算和下一步动作
- [x] 4.2 在审核开始前持久化 reviewing 状态，在审核结果应用后持久化释放或关闭状态，避免 provider 调用期间产生错误完成记录
- [x] 4.3 让 resume 继承审核门禁和修复预算，并阻止对 uncertain/in-flight 审核或发布操作的不安全重放
- [x] 4.4 将不可恢复审核失败映射为明确的 review_failed 或 review_retry_exhausted 终态，同时保持父运行记录不可变
- [x] 4.5 补充断线重连、恢复、重复审核、审核中断和终态竞争的 Gateway/检查点测试

## 5. 整理普通运行前端

- [x] 5.1 扩展协议类型，增加统一审核记录、ExecutionGate 和兼容旧事件的归一化映射
- [x] 5.2 实现共享 ReviewCard 与 ReviewTimelineItem，统一展示审核中、修复中、通过、警告、失败和耗尽
- [x] 5.3 在运行摘要和时间线明确显示“主链路已暂停”、审核 subject、问题、证据、下一步和剩余预算
- [x] 5.4 将测量 target/attempt/panel 与生成图 candidate/ChartSpec/VLM checks 接入审核详情展开区
- [x] 5.5 验证重连、历史缺口和旧事件下前端不会误显示为审核通过或已发布

## 6. 整理评测前端与验证

- [x] 6.1 让评测只读时间线复用统一审核组件和安全资源引用，保留测量审核与生成图审核的领域细节
- [x] 6.2 在评测详情中完整呈现审核开始、阻塞、修复、重试和最终未发布/失败结果
- [x] 6.3 增加端到端场景，验证测量审核和生成图审核都能阻塞主链路且只能通过受控修复释放
- [x] 6.4 运行 `conda run -n agent python -m pytest`、`npm run build`、`npm run smoke` 和 `git diff --check`
- [x] 6.5 更新受影响的 OpenSpec 主规格并记录兼容旧运行记录的行为
