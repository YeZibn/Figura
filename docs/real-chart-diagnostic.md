# 真实图表链路诊断

这套诊断只观察现有前端使用的 Gateway 链路，不直接实例化 Agent，也不直接调用图表工具。它的目标是回答“运行走到了哪里、哪一个阶段第一次出现了可确认异常”，不是建立通用的 OCR/测量精度评测集。

## 样本与清单

首批样本位于 `tests/fixtures/real_chart_diagnostic_manifest.json`，包括：

- `dashboard_text_two_bars_pie`：多面板文字 + 两个柱状图 + 饼图。
- `shareholders_and_adjusted_price`：股东人数与前复权股价折线图。

清单只允许相对于项目根目录的图片路径，并校验 SHA-256。修改图片后必须同步更新指纹；不允许把绝对路径、data URL、API key 或其他凭据写进清单。

## 运行环境与命令

Python 命令统一使用 `agent` Conda 环境：

```bash
conda run -n agent python -m chartagent.gateway --port 8765
```

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

也可以使用 `CHARTAGENT_EVAL_PROVIDER` 和 `CHARTAGENT_GATEWAY_URL`，但 provider 仍然必须明确存在。provider 不可用、Gateway 不可达或返回了不同 provider 时，命令会记录错误并退出，不会静默切换模型。

## 输出

默认输出到 `.chartagent/diagnostics/`，每个样本生成同名 `.json` 和 `.md`：

- JSON 是机器可读事实：样本指纹、run/provider/model、八阶段状态、事件序号、panel/attempt/artifact 引用、异常和第一个可确认失败。
- Markdown 是人工阅读视图：阶段表、未观察到的阶段、异常面板和最终引用。

报告只保留有界引用和错误摘要，不写入原图、模型原始提示词、API key、绝对本地路径或完整事件 payload。真实诊断输出不纳入默认 CI；固定事件样例覆盖应纳入 CI 的诊断规则。
