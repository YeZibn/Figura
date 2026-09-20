# 真实图表链路诊断

这套诊断只观察现有前端使用的 Gateway 链路，不直接实例化 Agent，也不直接调用图表工具。它的目标是回答“运行走到了哪里、哪一个阶段第一次出现了可确认异常”，不是建立通用的 OCR/测量精度评测集。

## 样本与清单

首批样本位于 `tests/fixtures/real_chart_diagnostic_manifest.json`，包括：

- `dashboard_text_two_bars_pie`：多面板文字 + 两个柱状图 + 饼图。
- `shareholders_and_adjusted_price`：股东人数与前复权股价折线图。

清单只允许相对于项目根目录的图片路径，并校验 SHA-256。修改图片后必须同步更新指纹；不允许把绝对路径、data URL、API key 或其他凭据写进清单。

## 运行环境与命令

Python 命令统一使用 `agent` Conda 环境：

先只校验清单，不会触发模型调用：

```bash
conda run -n agent python -m chartagent.evaluation \
  --manifest tests/fixtures/real_chart_diagnostic_manifest.json \
  --asset-root .
```

显式指定 provider 并确认执行一次真实链路：

```bash
conda run -n agent python -m chartagent.evaluation \
  --manifest tests/fixtures/real_chart_diagnostic_manifest.json \
  --asset-root . \
  --provider qwen \
  --case-id dashboard_text_two_bars_pie \
  --execute
```

执行真实评测时，命令默认会在评测包内自动启动一个 loopback Gateway，并在结束、失败或中断时回收它；不需要先手动启动 Gateway。每次执行都会创建新的
`.chartagent/evaluations/<evaluation_id>/`。如果需要指定根目录，可以使用：

```bash
conda run -n agent python -m chartagent.evaluation \
  --manifest tests/fixtures/real_chart_diagnostic_manifest.json \
  --asset-root . \
  --provider qwen \
  --data-dir .chartagent \
  --evaluation-root .chartagent/evaluations/manual-batch \
  --execute
```

显式指定的 `--evaluation-root` 必须尚不存在，避免覆盖旧评测。也可以只传
`--data-dir`，系统会在其 `evaluations/` 下自动生成唯一目录。

也可以使用 `CHARTAGENT_EVAL_PROVIDER`。如果传入 `--base-url`、设置
`CHARTAGENT_GATEWAY_URL` 或显式加入 `--external-gateway`，则进入旧的外部 Gateway
兼容模式：命令不会托管 Gateway，也不会把 Gateway 的数据库和附件纳入同一个评测包，
只写入诊断报告。该模式适合已有 Gateway 的快速检查；要获得完整、隔离的评测材料，
应使用默认托管模式。provider 不可用、Gateway 不可达或返回了不同 provider 时，命令
会记录错误并退出，不会静默切换模型。

## 评测包布局

一次完整评测的所有持久化材料位于同一个目录：

```text
.chartagent/evaluations/<evaluation_id>/
├── evaluation.json       # 批次索引与生命周期状态
├── manifest.json         # 本次选择的安全清单快照
├── summary.json
├── summary.md
├── sessions.db           # Gateway 原始历史，仅供本地诊断
├── attachments/          # 上传附件，仅供本地诊断
├── run-artifacts/        # 运行产物，仅供本地诊断
└── diagnostics/
    ├── <case_id>.json
    └── <case_id>.md
```

`evaluation.json` 和 `summary.*` 会在创建批次、每个 case 结束以及批次终止时更新。
状态含义如下：

- `running`：批次已创建，仍有 case 在执行。
- `completed`：所有选中的 case 都正常完成。
- `partial`：至少有 case 失败、超时或进程中断，但现场被保留。
- `blocked`：Gateway/provider 未能让 case 提交运行，或批次在启动阶段被阻塞。

JSON 是机器可读事实：样本指纹、run/provider/model、阶段状态、事件序号、panel/attempt/artifact
引用、异常和第一个可确认失败。Markdown 是人工阅读视图：阶段表、未观察到的阶段、异常
面板和最终引用。

报告与清单快照只保留有界、脱敏内容，不写入原图、模型原始提示词、API key、Authorization
头、`.env` 或绝对本地路径。`sessions.db`、`attachments/` 和 `run-artifacts/` 是本地取证材料，
不应直接上传或当作可分享报告。

旧的 `.chartagent/diagnostics/` 报告和共享数据不会自动迁移；新评测使用新的批次布局。
如果只需要旧式报告输出，可显式传入 `--base-url` 并配合 `--output-dir`。真实诊断输出
不纳入默认 CI；固定事件样例覆盖应纳入 CI 的诊断规则。

## 前端评测工作台

启动默认 Gateway 后，桌面端左侧的“评测”工作区会只读发现当前 canonical data root
下的 `.chartagent/evaluations/` 批次。它不会把评测 session 复制进普通会话列表，也不会
在评测页提供发送消息、继续、重试或删除操作。

工作台使用以下只读接口：

```text
GET /api/v1/evaluations
GET /api/v1/evaluations/{evaluation_id}
GET /api/v1/evaluations/{evaluation_id}/cases/{case_id}
GET /api/v1/evaluations/{evaluation_id}/cases/{case_id}/history?after={sequence}
GET /api/v1/evaluations/{evaluation_id}/cases/{case_id}/history/details?after_record={record_sequence}
GET /api/v1/evaluations/{evaluation_id}/resources/{resource_id}?case_id={case_id}
```

接口只返回有界的批次、case、阶段和失败摘要。图片必须使用返回的评测 resource reference
加载；`sessions.db`、绝对路径、`.env`、凭据和原始 provider payload 不会通过评测 API
暴露。`report.md` 与 `report-assets/` 是可选扩展：缺少它们时，工作台仍展示标准
`summary`/`diagnostics` 内容。

`history` 现在直接返回与普通会话 `RunHistory` 兼容的安全事件 payload。评测页复用普通会话的
只读 `RunTimeline`：工具调用和结果按 `call_id` 合并，参数/结果可展开、复制 JSON，视觉观察会
挂载到对应工具步骤，审核、测量修复、失败、恢复和终态事件按相同顺序展示。`history/details` 只
补充用户/模型可见消息和没有对应 Gateway 事件的记录，不再是查看工具结果的前置条件；同一
`call_id` 的 `records` 工具消息不会再次渲染。

每个 history 响应还返回 `integrity`。`complete` 表示当前安全事件可完整读取，`redacted` 表示
敏感字段被隐藏，`unavailable` 表示旧 bundle 已经在持久化阶段截断且没有旁路资源。结构化图表
数据使用语义化有界投影，保留 bbox、polygon、axes、baseline、bars、series 和 points 的数值，
不会因为嵌套层数本身被替换成摘要；集合、文本和总大小仍有明确上限。

新评测中超过普通事件 envelope 的安全 payload 会写入
`run-artifacts/history-details/<run_id>/<sequence>.json`，事件只保留工具身份、`call_id`、状态和
opaque `detailResource`。前端在工具结果卡片内按需加载该 evaluation/case-scoped JSON；资源读取
仍校验归属、白名单、字节上限和媒体类型。旧 bundle 没有该资源时继续显示已有安全结果，并明确
提示“不可恢复”，不会伪造完整内容。私有推理、凭据、绝对路径、data URL 与二进制内容不会下发，
普通会话的运行记录和评测的只读边界不受影响。

`running` 批次在评测工作区打开时会以固定间隔有限刷新；批次进入 `completed`、`partial`
或 `blocked` 后停止轮询。刷新失败会保留最近一次成功快照，并提供显式重试入口。
