# 压缩后资源目录直接读取试验

## 目的

验证压缩请求中的类型化资源引用能否引导模型直接调用 read_history，并读取完整的 OCR、测量或 ChartFigure 内容。另设引用未进入目录的对照，观察模型是否转用 search_history。

## 方法与边界

- OCR、测量和 ChartFigure 结果是确定性合成数据，按合法工具结果写入隔离 Session 的 Run 事实；本试验不评价 OCR 或测量准确率，也不把白图像素当作证据。
- 使用真实 Provider 生成一次压缩摘要，并用生产 AgentRequestBuilder 构建压缩请求。直接读取组显式保留三个资源生产 ToolResult 的来源引用，并从摘要中移除包含目标答案的摘要条目，以确保资源引用可见而答案必须从完整资源读取。因此直接读取组隔离评估“引用可见时”的读取行为，不评价摘要模型能否自然保留每个资源引用或不泄漏目标答案。
- 对照组从检查点中移除一个目标来源引用，确认资源目录不再展示该资源；完整 canonical Run 事实仍在，search_history 可按需发现它。
- 模型只能执行 read_history 与 search_history；其他工具调用以只读拒绝结果处理。调用通过生产历史工具运行时执行，但不是完整 Gateway/Agent Run。
- 每个用例使用真实模型一次。成功标准：目录引用可见、请求未泄漏答案、首个工具调用为 read_history、引用与目录完全一致、读取结果包含答案、最终答案正确。

## 运行

运行命令：

```bash
conda run -n agent python evaluation/history-resource-read-pilot/run_resource_read.py --batch-id <new-batch-id>
conda run -n agent python evaluation/history-resource-read-pilot/run_typed_resource_read_followup.py --source-batch <existing-batch-id>
```

主结果写入 `runs/<batch-id>/report.json`。已完成批次 `20261103-resource-direct-read-04`，完整分析见 [runs/20261103-resource-direct-read-04/report.md](runs/20261103-resource-direct-read-04/report.md)。

本批次中，自由选择组 6 题只有 1 题完成严格意义上的类型化目录引用读取并正确作答；定向读取组明确要求模型复制目录引用、直接调用 `read_history` 且省略 selector，OCR、测量、ChartFigure 各 1 题均读取并回答正确（3/3）。因此结论是：直接读取能力可用，但小样本自由选择表现不稳定。该结果是检索能力试验，不是完整端到端任务成功率或真实图片识别准确率。

合成运行时数据写入被忽略的 `.figura/evaluation/`。`evaluation/` 下的材料是可审阅的评测脚本、报告和结果，不属于运行时缓存。
