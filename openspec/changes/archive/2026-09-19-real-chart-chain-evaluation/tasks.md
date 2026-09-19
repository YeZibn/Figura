## 1. 最小样本与真实运行入口

- [x] 1.1 定义最小真实样本清单，登记多面板图片和折线图图片的 `case_id`、相对资源引用、内容指纹及预期面板信息。
- [x] 1.2 实现清单校验，拒绝绝对路径、缺失图片和指纹不匹配，并输出可定位的错误。
- [x] 1.3 实现显式 provider 配置和 Gateway 运行适配，通过现有附件上传、run 创建和历史/SSE 边界提交样本；provider 不可用时不得静默回退。

## 2. 运行事件阶段化

- [x] 2.1 将已有 run/event、panel、measurement、repair 和 artifact 事件归一化为 input、decomposition、panel_handoff、measurement、quality_review、repair、assembly、render 八个阶段。
- [x] 2.2 为每个阶段记录状态、事件 sequence、panel/attempt/artifact 引用和有界错误摘要，区分 `completed`、`failed`、`not_reached` 和 `not_observed`。
- [x] 2.3 处理运行中断、历史不完整、重复拆分和多面板整图测量，保留已到达阶段并生成明确异常标记。

## 3. 诊断报告与失败归因

- [x] 3.1 定义有界 JSON 诊断结果，保存样本、run、provider/model、阶段时间线、证据引用和最终产物引用。
- [x] 3.2 从 JSON 生成 Markdown 摘要，展示阶段流程、未到达阶段、异常面板和第一个可确认失败阶段。
- [x] 3.3 实现最小归因规则，支持 `decomposition`、`panel_routing`、`measurement`、`repair`、`assembly_render`、`transport_runtime` 和 `unknown`，并复用现有脱敏边界。

## 4. 验证与首批真实诊断

- [x] 4.1 使用固定事件样例测试完整运行、审核/修复失败、重复分区、未作用域测量、装配遗漏和证据不足场景。
- [x] 4.2 在显式 provider 开关下运行两张真实图片各一次，确认报告能够回答拆分、路由、测量、修复和装配问题；不把结果纳入默认 CI。
- [x] 4.3 编写诊断运行说明，记录 `agent` Conda 环境、provider 配置、真实调用开关、报告位置和敏感信息限制。
- [x] 4.4 运行相关 pytest、完整 `conda run -n agent python -m pytest -q` 和 `git diff --check`，确认现有契约测试保持通过。
