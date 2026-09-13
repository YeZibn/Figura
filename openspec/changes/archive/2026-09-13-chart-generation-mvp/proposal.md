## Why

Figura 当前可以从图像恢复结构化 `ChartSpec`，但还不能把识别结果或用户提供的数据重新渲染成可查看、可下载的图表。补齐这条反向链路可以验证理解结果、支持图表重绘，并让 Figura 从单向分析工具发展为可往返处理图表的工作台。

## What Changes

- 新增基于现有 `ChartSpec` 的确定性图表渲染能力，支持柱状图、折线图、饼图和散点图。
- 新增 Agent 可调用的图表渲染工具；渲染前校验 `ChartSpec`，失败时返回结构化错误，不让模型直接生成像素或未经校验的图像。
- 将生成图表作为有明确媒体类型和生命周期的 artifact 暴露给 Gateway，并支持运行过程中预览以及会话历史中的受控读取。
- 前端增加生成图表的预览、下载和运行记录展示，并区分用户最终生成物与模型自验证用的临时视觉观察。
- 第一阶段使用统一默认样式，不引入主题编辑、拖拽编辑、复杂堆叠布局或高级图表样式配置。

## Capabilities

### New Capabilities

- `chart-generation`: 从合法 `ChartSpec` 生成受限、可验证的图表 artifact，并支持 Agent 调用和结果校验。

### Modified Capabilities

- `desktop-client`: 展示生成图表的预览、下载入口、生成状态和错误信息。
- `python-gateway`: 管理生成图表 artifact 的创建、授权读取、持久化和清理。

## Impact

- 影响 `ChartSpec` 的消费端、图表工具注册、Agent 运行时、Gateway artifact 协议与 React 前端。
- 需要在 `agent` Conda 环境中提供确定性渲染依赖，并保持生成结果有界、可序列化且不暴露本地路径。
- 生成工具应复用现有工具结果、视觉观察和运行历史边界，不改变现有图片理解工具的调用方式。
