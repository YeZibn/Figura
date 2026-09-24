## 1. 修复工具批次与 repair 上下文顺序

- [x] 1.1 将一次 assistant tool-call 响应的 repair action 暂存到当前批次，确保所有对应 `tool` 消息按原调用顺序写入后才追加 continuation user 消息
- [x] 1.2 将同一批次的多个 repair action 按 attachment、panel、session、attempt 建立有界集合，保留每个父子 attempt 和受影响字段，禁止后到 action 覆盖先到 action
- [x] 1.3 保持视觉观察消息、tool 消息和聚合 repair 消息的稳定顺序，并确保无 repair 时不额外注入 continuation 消息

## 2. 保持 checkpoint 与恢复兼容

- [x] 2.1 将 checkpoint 的待处理 repair 状态升级为有界列表，并从旧的单数 `pendingMeasurementRepair` 字段兼容读取
- [x] 2.2 让 prompt runtime state、measurement session 和恢复上下文使用同一份 pending repair 投影，确保定向重测仍绑定当前 attachment、panel 和父 attempt
- [x] 2.3 校验 repair 已接受、被拒绝、耗尽和模型请求失败时的状态清理，避免恢复时重复执行或丢失未处理 panel

## 3. 改进模型失败与评测阶段诊断

- [x] 3.1 在 provider 客户端边界提取有界、脱敏的错误类型、状态、错误代码和摘要，并保持不记录密钥、路径、图片和完整 provider payload
- [x] 3.2 在评测 timeline 中纳入 model 请求事件，优先使用实际 `model_completed` 错误确定首个失败，禁止将 transport/model 失败回退标记为 render
- [x] 3.3 区分工具返回成功、measurement `remeasure_required`、repair pending/blocked/resolved 和后续阶段 `not_reached` 状态，更新 JSON/Markdown 投影

## 4. 回归测试与真实评测验证

- [x] 4.1 增加多工具调用中首个测量触发 repair 的消息顺序测试，断言所有 tool 结果连续出现且 repair 消息位于批次之后
- [x] 4.2 增加同一批次多个 panel repair 不覆盖、checkpoint 新旧字段兼容和恢复 lineage 的测试
- [x] 4.3 增加 provider 错误摘要与评测首个失败阶段归因测试，覆盖 assemble/render 未到达的场景
- [x] 4.4 使用现有 `bar_line_dashboard` 评测样本重新运行真实链路，确认报告不再把模型请求失败显示为 render，并记录修复后实际到达的阶段
- [x] 4.5 运行相关 pytest、完整 pytest、OpenSpec 严格校验和工作区 diff 检查，确认本 change 未引入绘图测量算法范围外的变更
