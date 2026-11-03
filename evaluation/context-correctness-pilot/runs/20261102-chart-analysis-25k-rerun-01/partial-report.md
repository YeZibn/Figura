# 图表分析 25k 压缩重跑：未完成

本批次按同一固定三轮对话重跑图表分析的 25k 压缩组和 100M 基线，二者使用独立 Session。基线三轮完成；压缩组首轮中断。

## 压缩组执行记录

- 第 1 轮期间成功完成 1 次上下文压缩；随后一个 Provider stream 约 12 分钟没有新事件，Run 一直处于 `running`。
- 为结束无输出请求，通过 Gateway 提交 stop；Run 最终为 `interrupted`。未提交第 2、3 轮，没有最终回答。
- 记录 Provider usage **46,323 Tokens**，其中至少 1 个 Provider attempt 缺少 usage；该数字不代表完整轮次总量。
- Provider attempt 的已记录响应字节数为 171,938；终态为 cancelled / connection error。完整证据见本目录 `01-chart-analysis__compaction/`。

## 评分与比较边界

Codex 按固定 scorecard 判定本批次 100M 基线通过。压缩组未完成端到端任务，按任务失败记录；由于只完成首轮且 usage 不完整，不能计算 Token 节省率。summary 中的 79.99% 是完整三轮基线与压缩组部分首轮之间的原始差异，不可比较。

逐项评分见 [`scorecard-results.md`](scorecard-results.md)。此重跑独立保留，不与此前 25k 运行或 50k 标准批次拼成同一个 Session 或 Token 配对。
