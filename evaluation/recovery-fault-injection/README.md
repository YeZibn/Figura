# 断点恢复进程级故障注入评测

本评测使用真实 SQLite 持久化、真实 `RunDispatcher` / `AgentExecutor` 恢复路径和本地 Fake Provider。每个故障用例都在独立子进程中运行，在指定持久化边界暂停后由父进程直接 `kill` 子进程，再以新进程从同一数据目录恢复。测试不访问真实模型服务，不产生 API 用量；输入、附件和工具副作用均为合成数据。

## 覆盖矩阵

12 个故障边界各重复 3 次，共 36 次进程中断；另有 5 次双 Dispatcher 恢复进程同时扫描同一 Run 的竞争场景。故障边界包括恢复扫描前、Provider attempt 发送前/发送后/响应提交前后、ToolAttempt 提交后、工具执行后结果提交前、幂等本地副作用后、`reconcile_required` attempt 后、媒体安装后结果提交前、ToolResult 提交后，以及最终响应提交后。

双进程场景启动两套真实 `RunDispatcher` / `AgentExecutor` 恢复执行栈，评估跨进程 Run 所有权锁和持久化状态竞争。它没有启动 HTTP Gateway 服务。每次都从同一 Run 同时启动两个 Dispatcher，检查最终只有一份逻辑工具结果、最终答复和终态事件。

## 指标口径

- **可自动恢复成功率**：预期自动恢复的中断用例中，最终进入 `completed` 的数量 / 可自动恢复用例数。`reconcile_required` 用例不计入此分母。
- **恢复策略符合率**：恢复用例达到该故障类型预期的终态，包括未知副作用时按策略 fail closed。
- **状态一致率**：恢复后 SQLite 完整性、外键、终态事件、最终答复、工具调用/结果数量与预期一致。
- **重复副作用数**：独立效果账本中同一幂等键产生的重复效果。重复调用工具处理函数单独记录，因为 `replay_safe` 的处理函数可能按恢复策略再次执行。
- **媒体发布状态**：分别统计落盘 PNG 和已由 ToolResult 提交的媒体引用，验证中断后文件可暂存、但未提交前不对 Agent 可见，恢复后引用只提交一次。
- **双 Gateway 竞争正确率**：两个进程竞争恢复时，均达到唯一合法终态且没有重复逻辑结果的用例比例。

报告只描述本地 Agent/Dispatcher 栈、Fake Provider 和测试文件系统下的结果，不外推为完整 Gateway HTTP 服务、真实 Provider 不确定结果、硬件/文件系统故障或生产环境可用性的成功率。

## 运行

```bash
conda run -n agent --no-capture-output python evaluation/recovery-fault-injection/run.py
```

也可以指定未使用过的批次名：

```bash
conda run -n agent --no-capture-output python evaluation/recovery-fault-injection/run.py --batch local-2026-11-03
```

每次运行创建独立的 `runs/<batch>/` 目录，保存汇总 `report.json`、每个用例的 `case-report.json`、隔离 SQLite 数据库和故障前后的合成执行证据。批次目录不会被覆盖。

评测脚本、任务材料、汇总报告和逐例 `case-report.json` 纳入 Git；`cases/*/data/` 内的 SQLite 数据库、WAL/SHM、锁文件和其他运行快照仅保留在本地，由根目录 `.gitignore` 定向忽略。
