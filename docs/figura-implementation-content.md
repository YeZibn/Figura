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

## 尚未拆分的后续方向

| 方向 | 当前状态 | 下一步 |
|---|---|---|
| Provider/Run 执行接入与 continuation 管理 | 计划方向，尚未建立 OpenSpec change | 先确定 continuation 合同，再拆分 change |
| ToolRegistry、附件授权、Prompt、Gateway/CLI/UI | 暂定方向，尚未形成完整方案 | 按依赖关系逐项讨论和拆分 |

## 工作入口

- 只读核实现状：`$figura-implementation-read`
- 写入已讨论方案：`$figura-implementation-plan`
- 按完成情况回填：`$figura-implementation-reconcile`
- 正式提案、实现、主规格同步和归档仍分别使用对应的 OpenSpec skill。
