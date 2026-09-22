## 1. 统一运行与错误契约

- [x] 1.1 在运行事件协议中增加有界的 process/turn/operation 关联字段和统一 failure envelope，保证新字段可选、可序列化、可脱敏，并兼容旧事件。
- [x] 1.2 在模型/provider 调用边界实现确定性拒绝与结果未知的分类，分别填充 failure category、稳定错误码、provider 状态、safe message、retryability 和 first failure ref。
- [x] 1.3 调整 terminal/recovery 处理：确定性 provider 拒绝只进入唯一 failed terminal outcome，timeout/连接中断等未知结果才进入 recovery-blocked；保留显式 retry/resume 的父子 lineage。

## 2. Source scope 与图表工具契约

- [x] 2.1 收紧 `generation_context` 的 JSON Schema、解析和运行时校验，使 source-linked mode、source-free synthesis、coverage 和 source scope 的条件一致。
- [x] 2.2 在已授权 attachment/panel/revision 唯一可解析时绑定 effective source scope，并在歧义、跨 panel 或 handoff 无效时返回字段级结构化错误。
- [x] 2.3 让 chart tool dispatch、measurement attempt 和 tool result 同时记录 requested/effective scope、绑定依据和 action hint，确保 scope 错误不产生 accepted evidence。
- [x] 2.4 更新图表工具的模型可见描述和结构化错误映射，明确 scope 绑定边界，不让工具替模型决定系列语义或静默扩大测量范围。

## 3. 执行事件与时间线投影

- [x] 3.1 为 run、model turn、tool operation 和 terminal lifecycle emitter 补齐可验证的过程关联及失败上下文，同时保持原始 run sequence 和旧事件读取兼容。
- [x] 3.2 更新服务端 decision timeline envelope，使 decision-unit 事件、过程事件和 legacy 事件遵循固定关联优先级，并保留原始事件作为事实来源。
- [x] 3.3 重构前端 timeline projector：按显式 unit、process/turn/operation、run-scoped legacy bucket 的顺序分组，取消按 event sequence 创建顶层 legacy 卡片，并保持 transition/sequence 幂等去重。
- [x] 3.4 保持 measurement、generation、review、publication 的既有 lineage 和 pending/blocked 语义，确认 lifecycle 容器不会被误解释为 candidate、审核或发布结果。

## 4. 普通运行与评测展示

- [x] 4.1 扩展前端协议类型、事件详情和错误摘要，优先展示结构化 failure category、provider status、字段 location、safe message 和 action hint，原始 payload 仍只读可展开。
- [x] 4.2 更新普通运行页面的中文过程标签和兼容历史提示，验证 test5 风格的加载、拆解、工具调用、provider 失败和终态可以连续阅读。
- [x] 4.3 让评测工作台复用普通运行的 timeline projector、错误映射和详情引用，禁止评测层重新压缩或重新解释 execution history。

## 5. 回放夹具与回归验证

- [x] 5.1 增加包含 run/model/operation/terminal lifecycle events、source-scope error 和 provider rejection 的混合回放夹具，并保留旧 test4 风格无关联事件夹具。
- [x] 5.2 为错误分类、terminal/recovery 选择、source scope 唯一绑定/歧义拒绝、effective evidence 绑定和旧事件兼容增加 Python 回归测试。
- [x] 5.3 为 timeline projector、错误详情优先级、实时追加与历史重放等价性、重复 sequence/transition 去重增加前端回归覆盖。
- [x] 5.4 验证普通运行、刷新、SSE 重连、显式 retry、评测只读读取和 test5 回放的分组、失败原因及终态一致；通过 `git diff --check`、`conda run -n agent python -m pytest -q`、`frontend` 下的 `npm run build` 与 `npm run smoke`。
