## Why

工具系统的"机制"（Tool 定义/注册/分发/序列化，add-tool-system 已归档）已经
就位。要让 agent 真正"能做事"，需要第一批具体、确定的只读原语作为它的
"手"——能读文件、能查目录、能解析结构化数据。本 change 用既有工具机制注册
一组纯只读工具，零副作用、安全，为后续 agent loop 提供第一个可安全调用的
能力面，也为图表理解侧的数据接入打底。

## What Changes

- 新增一组只读基础工具（全部经 `Tool` 定义、JSON 结果协议，天然满足 MCP
  预留），放 `src/chartagent/tools/builtin/`：
  - `read_file(path)` → 返回文件文本内容
  - `list_dir(path)` → 返回目录条目列表
  - `parse_json(text)` → 解析 JSON 文本为结果或结构化错误
  - `read_json_file(path)` → 读文件 + 解析（组合前两者）
- 提供统一入口 `register_builtins(registry)`，把内置工具一次性注册进
  `ToolRegistry`
- **本 change 明确只做只读工具**：不含写文件/删除等副作用工具、不含数据
  统计/文本类工具（留给后续 change），保证是安全切片

## Capabilities

### New Capabilities
- `basic-tools`: 一组只读基础工具（文件读取、目录列举、JSON 解析），通过
  `register_builtins()` 批量注册

### Modified Capabilities
<!-- 无：复用既有 tool-system 机制，不改其 requirements -->

## Impact

- 新增模块：`src/chartagent/tools/builtin/`（files.py / data.py /
  register.py）
- 复用：`Tool` / `ToolRegistry`（来自已归档的 tool-system）
- 无新增第三方依赖；不改动既有 client / conversation / tools 机制
- 新增单测：`tests/test_builtin_tools.py`（mock 直测，不依赖真实 LLM）