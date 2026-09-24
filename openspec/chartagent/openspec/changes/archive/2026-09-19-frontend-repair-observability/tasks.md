## 1. 接入测量修复事件

- [x] 1.1 将 `measurement_repair_required`、`measurement_repair_rejected` 和 `measurement_repair_exhausted` 加入 Gateway SSE 事件订阅白名单，并确认仍使用现有 `afterSequence` 游标。
- [x] 1.2 为前端修复事件定义受限的 payload 视图或类型守卫，只读取 panel、attempt、parent attempt、target、status、reason 和 next action 等允许字段，并为缺失字段提供安全降级。

## 2. 运行时间线展示

- [x] 2.1 为三类测量修复事件增加稳定的简体中文标签，保留英文事件类型作为技术标识和未知事件回退。
- [x] 2.2 在运行时间线中展示修复事件的有界摘要，明确区分“需要重测”“被拒绝”和“次数用尽”，且不改变运行终态、审核状态或发布状态。
- [x] 2.3 增加 required、rejected、exhausted 三种代表性前端事件样例，验证修复事件不会被错误归入普通工具步骤或成功结果。

## 3. 历史回放与重连一致性

- [x] 3.1 验证历史先到、实时先到以及重复事件到达时，修复事件均按 `runId:sequence` 去重并保持顺序。
- [x] 3.2 验证页面刷新、会话切换、SSE 断开重连和历史缺口场景下，既有修复事件仍可见且不会伪造完整或成功状态。
- [x] 3.3 增加未知修复相关事件的安全英文回退验证，确保未知事件不会阻断同一运行的后续事件。

## 4. 验证与交付

- [x] 4.1 更新前端 smoke 检查，固定三类事件名称、中文展示和事件订阅链路，避免后续再次遗漏 SSE 白名单或标签映射。
- [x] 4.2 在 `frontend` 目录执行 `npm run build` 和 `npm run smoke`，修复类型、构建或静态链路回归。
- [x] 4.3 运行 `git diff --check`，并复核界面展示未包含原始图片、绝对路径、密钥或 provider 原始 payload。
