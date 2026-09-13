# Figura 对接说明

这是一份给后续开发对话使用的简版交接文档。项目是本地图表分析工作区，产品名为 Figura，Python 包名仍保留 `chartagent`。

## 新对话提示词

```text
你现在接手 /Users/yezibin/Project/Figura 的 Figura 项目。

先阅读 AGENTS.md、README.md 和 docs/Figura-integration-guide.md，再检查 git status --short。
不要回滚已有的未提交改动。Python 命令和测试必须使用 conda run -n agent。
真实前端联调使用 npm --prefix frontend run dev:gateway；npm --prefix frontend run dev 只是 mock。
当前主要修改 React 与 Python/Gateway，除非我明确要求，否则不要扩展 Tauri。
涉及行为变化时，先按 OpenSpec 的 explore、propose、apply、sync、archive 流程处理。
```

## 启动与验证

```bash
cp .env.example .env
npm --prefix frontend run dev:gateway  # 真实 Gateway + React，地址 1420
npm --prefix frontend run dev          # mock 模式，仅用于 UI 开发
curl http://127.0.0.1:8765/api/v1/health

conda run -n agent python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run smoke
```

默认端口：Vite `1420`，Gateway `8765`。`dev:gateway` 会管理它启动的子进程，使用 Ctrl-C 停止；不要同时启动多个实例。

## 结构入口

- `src/chartagent/agent.py`：Agent 循环、模型回合和工具调用。
- `src/chartagent/runtime.py`：组装 Agent、memory、附件和工具。
- `src/chartagent/client/`：OpenAI 兼容客户端与配置解析。
- `src/chartagent/tools/chart/`：OCR、柱/线/饼/散点图传感器、`ChartSpec` 和 `render_chart`。
- `src/chartagent/gateway/`：本地 HTTP、Run、SSE、历史、附件和图表 artifact。
- `frontend/src/`：React + TypeScript + Vite；`gatewayClient` 是真实接口，`mockClient` 是模拟接口。
- `tests/`：Python 测试；`openspec/specs/`：当前行为规格。

## 关键行为

图片上传只登记并持久化附件，不会自动发送给模型。Agent 需要视觉检查时调用 `load_image(attachment_id)`，也可以继续调用 OCR 和图表传感器。

一次提问对应一个 Run。Run 会持久化模型回合、工具调用、工具结果、视觉观察、生成图表和最终答案，并通过 SSE 增量展示。前端应保留执行详情，最终答案使用安全 Markdown 渲染；生成图表通过 artifact ID 预览或下载。

## 配置与约束

`.env` 优先使用 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`；不要提交或打印真实密钥。Gateway 默认只绑定回环地址，附件和 Run 使用 opaque ID。

用户界面使用简体中文。新增协议字段要同时更新前端类型、Gateway 行为、测试和 OpenSpec。Python 使用四空格和 `snake_case`，React 组件使用 `PascalCase`；提交前运行 `git diff --check`。
