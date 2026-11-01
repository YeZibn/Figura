# 实施验证记录

## Provider 原生工具图片准入

2026-10-21 使用同一 Chat Completions 原生工具结果合同进行最小测试：两条不同 call ID 的 TOOL 消息，各含短文本和一个无答案泄漏的 256×256 PNG。要求按调用 ID 识别颜色与形状，关闭思考，只进行一次请求，不进行整套图表评测。

| 固定模型 | 官方合同证据 | 实测 | 是否启用 |
|---|---|---|---|
| DeepSeek / deepseek-flash | 官方 Chat Completions 明确 tool.content 可用 text / image_url 数组 | call_0 红色圆形、call_1 蓝色方形，全部正确；输入 717、输出 35、合计 752 tokens | 是 |
| Qwen / qwen3.8-flash | 官方 Chat Completions 将 tool.content 定义为字符串，不满足本次图片数组合同 | 403 PermissionDeniedError；不能据此推断模型不支持或可看见图片 | 否 |
| MiMo / mimo-v2.6-flash | 官方文档可见视图未展开 TOOL 字段；仍未确认精确图片合同 | 当前无有效配置，未发送 | 否 |

DeepSeek 合同：[官方接口文档](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)。Qwen：[官方 Chat Completions 文档](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)的 Tool Message 明确要求 content 为字符串，当前合同不能忠实表达图片；不从 user 多模态或 Responses 支持推导 TOOL 可用。MiMo 核对入口为[官方 Chat Completions 文档](https://mimo.mi.com/docs/en-US/api/chat/openai-api)，可读取视图没有展开 TOOL 字段，且当前无有效配置，能力仍未确认。Qwen 及 MiMo 不能以其他协议支持、HTTP 可连接或社区示例代替本接口识别验收。后续启用前必须补齐官方合同和识别验证。

本地准备入口依据 `ProviderPolicy.supports_tool_result_images` 拒绝未启用组合；具备图片结果的 Registry 在首次普通请求准备时已声明该需求，避免先花费一轮再发现不支持。不丢图、不追加普通 user 图片、不切换端点或模型。真实请求脚本与原始记录仅保存在 Git 忽略的 evaluation 目录，不提交配置、路径或凭据。

## 本地回归与验收

- 在 `agent` Conda 环境运行 `tests/test_figura*` 与 `tests/test_prompting.py`：799 项通过。随后针对最后调整的媒体字节和摘要完整性边界，运行 `tests/test_figura_tool_media.py`、`tests/test_figura_tool_runtime.py`：31 项通过；相关 CLI 测试 `tests/test_cli_agent.py`：23 项通过。
- 本地测量路径冒烟使用一个隔离 fixture manifest，覆盖同一组合样例中的柱状图、折线图、散点图、饼图，共 4 张图；`tool_errors=0`，没有 Provider／网络请求。运行器提示本地 `o200k_base` tokenizer 缓存未准备，因此此项只确认工具接线和离线执行成功，不记录 Token 数，也不作为测量准确率评测。
- 全仓库 `pytest`：1317 项通过、35 项失败、1 项跳过。将同一批 35 个失败节点在独立的 Git `HEAD` 基线目录重跑，失败集合完全一致；失败集中于旧 `chartagent` 测试依赖的缺失图片 fixture 或 manifest。Figura 本次实现没有新增这些失败。完整输出及节点对照保存在 Git 忽略的 `evaluation/multimodal-tool-results/`。
- 文档模型字段与本地链接审计通过：69 个涉及模型字段均有文档记录，445 个本地链接存在。`git diff --check` 与本 change 的 `openspec validate --strict` 均通过。
- 本 change 没有修改前端或启动器，因此未运行 npm build、smoke 或 launcher smoke；不据此声明完成 UI 验收。
- 显式 SQLite／Sources 迁移仅在隔离临时数据库与 fixture 上验证。本次没有迁移工作区实际 `.figura` 数据，也没有改变用户本地历史数据。
