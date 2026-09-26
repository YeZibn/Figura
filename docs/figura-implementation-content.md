# Figura 实现内容记录

> 本文是实现记录索引。每个已拆分的 change 有独立详细记录；实现事实以当前代码和可复核的验证结果为准。

## 阅读约定

- 先从索引定位 change，再进入对应详细记录。详细记录按“概览与决定、实现合同、核心流程、实现对照、验证与交接”组织。
- “已实现”必须有代码证据；历史验证结果须注明来源和是否本次重跑。计划、规格和实现状态分开记录。
- 设计稿与 `src/chartagent/` 仅作参考，不自动成为 Figura 决策。

## 状态含义

- **实施状态**：计划中、实现中、部分实现、已实现、暂缓。
- **OpenSpec 状态**：未建立、活动 change、主规格已同步、已归档。
- **决策状态**：已确认、暂定、待确认。

## Change 索引

| Change | 实施状态 | OpenSpec 状态 | 交付摘要 | 详细记录 / 后续交接 |
|---|---|---|---|---|
| `add-figura-model-client` | 已实现 | 主规格已同步、已归档 | Qwen、DeepSeek、MiMo 配置、请求/响应合同和适配器 | [Provider 基础层](figura-implementation/changes/add-figura-model-client.md)；continuation 私有数据持久化由后续 change 负责 |
| `add-figura-run-execution-core` | 已实现 | 主规格已同步、已归档 | Session、Run、SQLite 执行事实、checkpoint、幂等及安全事件 | [Run 与执行事实持久化基础](figura-implementation/changes/add-figura-run-execution-core.md)；Provider 请求执行由后续 change 接入 |
| `add-figura-tool-runtime` | 已实现 | 主规格已同步、已归档 | 共享 JSON Schema 校验、不可变 Registry、Provider 工具投影和单次安全 dispatch | [Figura 工具运行时基础设施](figura-implementation/changes/add-figura-tool-runtime.md)；不含 Run 持久化或 Agent loop |
| `add-figura-durable-tool-execution` | 已实现 | 主规格已同步、已归档（17/17 tasks 完成） | 独立持久化工具调用意图、attempt 与结果，按顺序执行并通过 per-Run 锁和 replay_effect 恢复未知结果 | [Figura 持久化工具执行](figura-implementation/changes/add-figura-durable-tool-execution.md)；不含 Provider continuation 与 ReAct 调度 |

## 尚未拆分的后续方向

| 方向 | 当前状态 | 下一步 |
|---|---|---|
| Provider continuation 持久化 | 尚未建立 OpenSpec change；依赖 durable tool execution | 定义私有 continuation 的持久存储、恢复与 Provider 历史重建合同 |
| Agent ReAct 核心循环 | 尚未建立 OpenSpec change；依赖工具设施与 durable execution | 建立唯一 AgentExecutor、从记录重建 history、限制模型/工具轮次并接通 Provider 与 ToolRuntime |
| 首批图表工具、来源/附件授权与呈现层 | 暂未拆分 | 等 Agent core 合同明确后，逐个领域工具讨论输入、输出、权限和副作用；再接 Gateway/CLI/UI |

## 工作入口

- 只读核实现状：`$figura-implementation-read`
- 写入已讨论方案：`$figura-implementation-plan`
- 按完成情况回填：`$figura-implementation-reconcile`
- 正式提案、实现、主规格同步和归档仍分别使用对应的 OpenSpec skill。
