# Figura 30 项端到端任务评测材料 v1

准备日期：2026-11-02。状态：**材料准备与离线检查；未执行正式 Agent 任务，未得到成功率。**

本目录保留本地评测材料，受仓库 `/evaluation/` 忽略规则管理。本次不修改在线 Agent、Prompt、工具或 OpenSpec 行为合同。材料检查记录见 [validation-report.json](validation-report.json)。

## 入口

- [30 题清单](TASKS.md)：类别、轮数、输入及参考答案入口。
- [运行协议](protocol.md)：执行条件、证据采集、产物选择、失败与复核。
- [Codex 评判提示](judge/prompt.md)：每题独立上下文使用，不与 Figura 共享。
- [评判结果 JSON Schema](judge/verdict.schema.json)：正式裁决结构。
- [独立复核提示](judge/review-prompt.md)。
- [评判校准材料](calibration/README.md)：3 个正式集外案例，包含正确结果和刻意错误结果。
- [批次配置模板](templates/batch.json)、[逐题执行记录模板](templates/execution.json)。
- [报告模板](templates/report.md)。
- [来源说明](sources/README.md)：6 张合成图与 4 张真实来源图的边界。
- [准备阶段发现](known-material-findings.md)：材料纠正和当前原生环图渲染的可读性风险。
- [准备环境](preparation-environment.json)：参考图生成所用版本与代码摘要。
- [完整文件摘要](checksums.json)：准备检查完成后的文件 SHA-256。

## 材料布局

```text
tasks/A01 ... A10/     图片理解与分析：每题 1 轮
tasks/B01 ... B10/     结构化数据构建：每题 1 轮
tasks/C01 ... C10/     已有图表多轮修改：每题 3 轮
  task.json
  agent-input/
    conversation.json 固定对话；每轮 text 即实际用户消息
    conversation.md   便于人工按轮复制
    chart.png         仅 A 类首轮附件
    dataset.json      仅 B/C 类；已嵌入首轮 text，不上传 JSON 文件
  judge-only/
    answer-key.json   所需事实、关键项、容差、证据要求
    scorecard.md      人工可读评分表
    reference-turn-XX.json / .png  B/C 类每次交付的语义参考
    change-contract.json          C 类各轮允许变化与保留约束
```

一个任务计为一个样本，不按 Run、工具调用、图片或轮数增加分母。正式集共 30 个独立 Session、50 轮固定用户消息。C 类每轮都明确要求实际渲染交付，任何一轮关键交付失败均影响任务整体结果。

## 输入隔离

只向 Figura 提交 `agent-input/conversation.json` 的当轮 `text` 和 `attachments`。不要上传 Markdown、整个任务目录、参考答案、来源 CSV、参考 ChartSpec、评分表、校准答案或索引。B/C 的 dataset 已内嵌在首轮用户消息，不重复发送。A 类仅首轮上传 chart.png，不发送底表。

这是基于正常 Gateway 工具边界的隔离约定。如果未来执行者拥有仓库任意文件访问能力，必须复制 `agent-input/` 到独立工作目录并限制文件访问；仅靠命名为 judge-only 不构成权限隔离。

## 当前范围

测真实 Gateway → Runtime/Agent → Provider/工具 → 回答和产物；UI 上传/预览/下载 smoke 单列，不混成浏览器全流程成功率。任务限制在当前 ChartFigure/ChartSpec v2 可表达范围，不考任意精确配色、轴范围/步长、在线正式审核或发布服务。

Codex 是评判官；可以使用确定性计算辅助核对，但必须独立看实际产物。参考 PNG 只用于解释预期语义，不用于逐像素匹配，也不是 Figura 已执行成功的结果。B08 的原生环图存在百分比遮挡风险，保留原生诊断图并另附独立视觉示意；题目及可读性标准不因此放宽。

## 冻结边界

输入、参考答案、容差和评分提示按当前版本准备，checksums.json 用于检测之后的变化。正式运行前还需填入真实 Provider/model/Codex 标识、版本摘要和校准得到的统一超时预算；这些是执行配置，不应凭空填写。先完成校准，再冻结正式批次。正式执行后改题、改容差或改判分规则必须产生新数据集版本和新批次，保留旧记录。
