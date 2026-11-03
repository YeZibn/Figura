# 25k 图表分析压缩续跑：未完成

该批次独立重跑图表分析 25k 压缩条件的固定三轮对话。与 50k 标准批次、原始 25k 部分批次及后续 25k 续测批次分别保存。

## 执行结果

- 第 1 轮在 30 分钟单轮上限后被停止，Run 状态为 `interrupted`，未提交最终回答；第 2、3 轮未完成。
- Provider attempt 共 90 次；已记录 usage 为 **2,098,542 Tokens**，其中有 1 个 attempt 缺少 usage，因此该数值不是完整总量。
- SQLite 中有 37 次压缩操作完成、另有 1 次操作停在 `preparing`。完整操作和调用证据保存在同目录 Gateway SQLite 中。
- 运行器收到中断终态后尝试提交下一轮，Gateway 返回 HTTP 500。该 Session 不再继续使用。

## 结论边界

此轮证明 25k 条件下发生了大量压缩和重复 Agent/工具调用，但没有完成端到端任务，也没有完整 usage，不能计算压缩节省率或压缩后任务成功率。它按一次失败任务留档，不与后续 25k 批次拼接成同一 Session 或 Token 配对。

后续批次从独立图表分析基线和图表构建/修改配对项继续，见 [`20261102-context3cat-stress-25k-continue-02`](../20261102-context3cat-stress-25k-continue-02/report.md)。
