## 1. 提示资产与加载

- [x] 1.1 新增 image_feedback.md 的 Common 与四类 Rules/Cue，明确候选观察、可见范围、有依据修正和自主继续原则。
- [x] 1.2 在 loader 中实现封闭段落解析与完整性校验；将完整资产内容加入稳定 SYSTEM 层，保持现有资产相对顺序和摘要隔离，使规则及 Cue 变化参与 prompt_digest。

## 2. 图像回传集成

- [x] 2.1 在 prompting 内实现四类反馈分类与邻近 TextBlock 构造，身份使用 JSON 编码，区分 resource_ref 和当前 trigger_call，不改变 Provider 模型。
- [x] 2.2 接入 load_image、extract_text、measure_chart、render_chart_figure 的实际图片输出，保留完整批次、授权校验、图像顺序和已有 source 去重。
- [x] 2.3 接入 read_resource_image，按权威资源类型复用四类提示并保留历史 origin；普通 JSON、失败调用和未加载的历史资源不附加局部提醒。

## 3. 行为与恢复验证

- [x] 3.1 补充 prompting/request 测试：四类提醒、混合批次、逐图邻近引用与触发调用、原图去重、无图不触发、历史 OCR/measurement/rendered 分类及资源授权不变。
- [x] 3.2 补充资产缺失/重复/空段、指令样式资源名称、提示身份变化与摘要不加载图像提示的回归。
- [x] 3.3 补充 executor/恢复回归，确认批次后仍走正常 MODEL、没有额外审核请求、相同前缀确定性重建、旧绑定变化沿原有拒绝路径处理，Provider-private continuation 保持准确关联。
- [x] 3.4 在 agent Conda 环境运行窄范围 prompting/request/executor 测试及完整 Python 测试，区分既有失败和新增失败，运行 git diff --check。

## 4. 文档与效果观察

- [x] 4.1 更新 Agent 领域文档与系统总览，描述新资产、图像分类、邻近身份、构造期生命周期、恢复和无门控边界，不把观察引导称为正式审核。
- [x] 4.2 以类别遗漏、图例误检、文字遮挡和多图连续任务进行小规模真实模型观察，记录条件与实际决策；Provider 不可用时明确记录行为验证缺口，禁止以 stub 成绩代替真实效果。
- [x] 4.3 严格验证本 change，核对代码、文档、规格与范围一致；保持主规格同步、归档和提交作为后续明确操作。
