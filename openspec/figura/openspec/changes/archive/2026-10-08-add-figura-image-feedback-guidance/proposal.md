## Why

Figura 已将原图、OCR/测量标注图和生成 PNG 回传主 Agent，但图像旁主要只有身份说明，固定工作流中的回看规则缺少针对当前图像的提醒。需要在既有反馈路径提供清晰、分类型的观察引导，使模型利用图像发现问题并自主决策，而不建立额外审核流程。

## What Changes

- 新增独立 `image_feedback.md` 提示资产，覆盖 original、ocr、measurement、rendered 四类图像反馈。
- 每张实际附加的图片之前增加简短观察提醒和明确资源身份；原图按需理解，标注图检查遗漏/误检/关联，生成图检查任务对应与可见布局。
- 当前工具自动回传和 `read_resource_image` 显式重载使用相同分类；普通 JSON 结果、资源索引和没有实际图片的请求不触发图片提醒。
- 保持完整工具批次、图像授权、现有数量/顺序与去重语义；不新增 Provider 请求、工具、审核状态、门控或数据库字段。
- 提示资产参与现有请求指令身份，补充请求构造、历史图像和恢复回归，更新 Agent 领域文档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-react-execution`: 为实际回传图像增加来源关联、类型化观察提醒与自主后续决策约束。

## Impact

主要涉及 `src/figura/agent/prompting/observations.py`、`loader.py`、提示资产与必要的 `request.py` 协调；测试涉及 Figura prompting/request/executor，文档涉及 Agent 与系统总览。Provider 消息字段、工具 Schema、Runtime 动作/持久化、前端协议及旧 chartagent 均保持现有合同。模型注意力和请求 token 用量会有所变化；不宣称检查准确率或生成质量已经提高。
