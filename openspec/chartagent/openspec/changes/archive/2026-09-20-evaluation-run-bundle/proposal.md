## Why

一次真实图表评测目前只把 JSON/Markdown 报告写入共享的 `diagnostics/`，而 session 数据库、上传附件和观测 artifacts 仍混在全局 `.chartagent/` 下。这样无法从目录本身还原一个评测批次，也容易把本次结果与历史 run 混淆；当前已经需要保留失败现场和完整运行材料，因此应在评测开始前建立独立的评测目录。

## What Changes

- 为每次评测批次生成稳定的 `evaluation_id` 和独立目录。
- 在评测目录内保存清单快照、运行元数据、批次汇总、每个 case 的诊断报告和 Gateway 运行数据。
- 让评测使用该目录作为 Gateway 的独立 data root，使 `sessions.db`、`attachments/`、`run-artifacts/` 与诊断输出天然属于同一次评测。
- 保留现有 Gateway 评测链路、provider 显式选择、样本指纹校验和 JSON/Markdown 报告格式。
- 评测结束或中断时都写入批次状态和已完成 case 的引用，支持后续从同一目录复盘。
- 不把 API key、环境文件或未经脱敏的敏感 provider 响应复制进评测清单和可分享摘要。

## Capabilities

### New Capabilities

- `evaluation-run-bundle`: 定义一次评测批次的独立目录、元数据、清单快照、运行材料和生命周期状态。

### Modified Capabilities

- `real-chart-evaluation`: 要求真实评测在独立批次目录中执行并产出批次级索引，同时保持现有 Gateway 观察链路和诊断阶段语义。

## Impact

- 影响 `src/chartagent/evaluation/` 的 CLI、Gateway 评测客户端、报告写入和批次汇总逻辑。
- 影响 Gateway 启动时的 data-root 注入，以及 `.chartagent` 下评测数据的目录布局和清理策略。
- 需要更新真实评测文档、配置帮助和回归测试；不改变图表传感器、Agent 工具协议或前端图表功能。
