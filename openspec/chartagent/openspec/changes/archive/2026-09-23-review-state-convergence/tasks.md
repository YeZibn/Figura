## 1. 收敛审核状态模型

- [x] 1.1 将 candidate、review、repair lineage、publication 和 idempotency 状态收敛到 `ChartReviewManager` 管理的单一 generated-review 聚合中
- [x] 1.2 将 run gate 改为从未 supersede 的候选聚合即时计算，并让 prompt、工具授权、终止检查和 checkpoint 使用同一投影入口
- [x] 1.3 移除 `ReviewCoordinator`、重复的 `ReviewRecord`/`ReviewDecision` 状态、`GeneratedChartReviewAdapter`、无生产调用的 `MeasurementReviewAdapter` 及相关旧导出
- [x] 1.4 保留必要的不可变 `ExecutionGate` API 投影，并确保集合父子候选、重试和 supersede 语义一致

## 2. 整理审核执行和事件

- [x] 2.1 将确定性 artifact 检查结果传递到审核完成转换，确保每个 candidate attempt 只执行一次
- [x] 2.2 保持确定性检查失败时跳过 VLM；检查通过时按策略调用一次 tool-free VLM，并校验 candidate、review 和 ChartSpec digest 后原子更新聚合
- [x] 2.3 让审核事件由聚合状态转换产生，保留一个 review identity 和一组最终结果字段，内部检查细节只进入有界技术 trace
- [x] 2.4 将 Gateway execution gate 和 artifact review 字段改为从 canonical 状态转换更新的只读投影，并保留通过审核后才 promotion 的规则

## 3. 持久化和恢复收敛

- [x] 3.1 在审核调用前将候选图片与对应 ChartSpec 持久化到私有 generated-candidate 存储，并提供按 candidate identity 校验读取的接口
- [x] 3.2 为 `ChartReviewManager` 增加有版本的状态快照和恢复能力；checkpoint 只保存 canonical review 状态及候选引用，不再单独保存可恢复的 execution gate
- [x] 3.3 恢复时从候选存储重建审核输入并派生 gate；候选、ChartSpec 或 digest 缺失/不匹配时报告 bounded recovery error 并保持不可发布
- [x] 3.4 删除旧 split-state checkpoint 的 fallback restore；遇到旧形状时明确返回 unsupported review-state 错误，不默认打开 gate

## 4. 替换回归验证

- [x] 4.1 将 coordinator/adapter 内部测试迁移为单一聚合状态、gate 派生、重复调用幂等和候选发布状态一致性测试
- [x] 4.2 覆盖 deterministic 与 VLM 执行次数、审核身份稳定、错误结果 fail-closed、collection 子图混合结果和 superseded attempt
- [x] 4.3 覆盖审核开始前候选持久化、审核中断恢复、无效引用恢复失败、旧 checkpoint 明确拒绝及 promotion 幂等
- [x] 4.4 覆盖 Gateway 事件、run summary、候选预览和最终 artifact 都与 canonical review 聚合一致
