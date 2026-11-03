# 上下文压缩补充压力批次：25k（未完成）

本批次与预注册的 50k / 100M 结果分开保存，不作为三类压缩评测的正式结果。

## 已观察到的情况

- 仅启动了图表分析任务的 25k 压缩组；基线组和其余两个任务没有运行。
- 第 1、2 轮完成，第 3 轮 Run 最终记录为 `interrupted`。约接近 600 秒单轮上限时，运行器读取 Run history 收到 Gateway HTTP 500。
- 前两轮分别消耗 77,639 和 45,586 Provider Tokens，其中摘要压缩调用分别占 8,465 和 24,090 Tokens。
- 隔离数据库记录 14 次压缩操作完成、1 次因 `summary_source_ref_unauthorized` fallback；另有 1 次压缩 Provider 响应校验失败和 1 次被取消的传输尝试。第三轮未完成，剩余操作不作成功判定。

## 结论边界

25k 容量的触发线为 20k，实际触发了重复增量压缩，但在这组三轮图表分析任务中摘要开销偏高，且长 Run 在 Gateway history 轮询时返回 HTTP 500。由于没有配对基线、只完成一个任务的前两轮，本批次不能计算 Token 降幅或任务成功率；不将其与 50k 条件合并。

原始会话记录位于同批次目录；隔离 SQLite 和 Gateway 日志保存在 `.figura/evaluation/context-pilot-20261102-context3cat-stress-25k-01/`。
