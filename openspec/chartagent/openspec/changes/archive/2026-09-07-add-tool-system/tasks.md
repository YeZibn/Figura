# Tasks: add-tool-system

实现 add-tool-system。基线：`src/chartagent/` 已含 `client`(llm-client) 与
`conversation`（conversation-loop）。本 change 在 `src/chartagent/tools/` 下
新增工具系统，不含 loop。

## 1. Tool 定义

- [x] 1.1 新增 `src/chartagent/tools/tool.py`,定义 `Tool`（dataclass）:
  `name: str`、`description: str`、`parameters: dict`(JSON-Schema)、
  `fn: Callable`。提供校验:注册时 name 非空。

## 2. ToolRegistry

- [x] 2.1 新增 `src/chartagent/tools/registry.py` 的 `ToolRegistry`:
  `register(tool)`(重名抛/拒)、`get(name)`、`list() -> list[Tool]`、
  `__len__` 便于测试。

## 3. 分发与结构化结果

- [x] 3.1 在 registry 或单独模块实现 `dispatch(name, arguments_json)`:
  解析 JSON arguments → 调用对应 `fn(**args)` → 成功返回 JSON 字符串。
- [x] 3.2 统一失败路径:未知工具名、`fn` 抛异常、结果不可 JSON 序列化,
  均返回 `{"error": ...}` 结构,不向调用方抛异常。

## 4. MCP converter 骨架(预留,不搭 server)

- [x] 4.1 新增 `src/chartagent/tools/mcp_converter.py` 提供
  `to_mcp_tools(registry)` → `{"manifests": [{name,description,inputSchema}],
  "callables": {name: wrapper}}`,仅做形状映射、无 IO。
- [x] 4.2 附带一个示例工具映射演示（如一个 `echo`/算术工具经过转换后形状
  正确),用单测钉住协议。

## 5. 单测（mock 驱动,不依赖真实 LLM）

- [x] 5.1 新增 `tests/test_tools.py`:覆盖 Tool 定义、register/get/list、
  重名拒绝、成功 dispatch 返回 JSON、未知工具名/抛异常/不可序列化三种失败
  路径、MCP 转换形状。

## 6. 包导出与冒烟

- [x] 6.1 在 `src/chartagent/__init__.py` 导出工具系统公共符号
  （`Tool`、`ToolRegistry`、`to_mcp_tools`）。
- [x] 6.2 跑通全部单测（`pytest -q`,工具系统相关全绿）。
- [x] 6.3 写一个 mock 冒烟片段(如 `tests/` 或说明),演示注册→分发→取结果的
  最小闭环可运行(可选,不强求真实端点)。