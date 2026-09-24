# Tasks: add-basic-tools

实现 add-basic-tools。基线：`src/chartagent/tools/` 已有工具机制
（`Tool` / `ToolRegistry` / `dispatch`，add-tool-system 已归档）。本 change 在
`src/chartagent/tools/builtin/` 增加 4 个只读工具与统一注册入口，不含
副作用工具/统计/文本工具/loop。

## 1. 文件工具（只读）

- [x] 1.1 新增 `src/chartagent/tools/builtin/files.py`，定义：
  - `read_file(**kw)`：按 path 读取文本，成功返回内容，失败返回
    `{"error": ...}`（不存在/不可读）
  - `list_dir(**kw)`：按 path 返回目录条目列表，失败返回 `{"error": ...}`
- [x] 1.2 为两个工具定义 `Tool` 实例（name/description/parameters JSON-Schema，
  用关键字签名便于 dispatch 的 `fn(**args)` 调用）

## 2. 数据工具（JSON）

- [x] 2.1 新增 `src/chartagent/tools/builtin/data.py`，定义：
  - `parse_json(**kw)`：解析 JSON 文本，成功返回解析值，失败 `{"error": ...}`
  - `read_json_file(**kw)`：读文件后复用 `parse_json` 的解析逻辑，失败
    `{"error": ...}`
- [x] 2.2 为两个工具定义 `Tool` 实例（同上参数 schema）

## 3. 统一注册入口

- [x] 3.1 新增 `src/chartagent/tools/builtin/register.py`：
  `register_builtins(registry)` 把 4 个工具一次性 `registry.register(...)`。
- [x] 3.2 新增 `src/chartagent/tools/builtin/__init__.py` 导出
  `register_builtins`（及工具名清单）。

## 4. 单测（mock 直测，不依赖真实 LLM）

- [x] 4.1 新增 `tests/test_builtin_tools.py`，用临时目录/临时文件覆盖：
  - `register_builtins` 后 registry 可 `get` 到全部工具
  - `read_file` 成功/缺失文件错误；`list_dir` 成功/缺失目录错误
  - `parse_json` 有效/无效 JSON；`read_json_file` 成功/缺失或坏 JSON 错误
  - 全部结果经 `dispatch` 返回，符合 JSON 结果协议

## 5. 冒烟与全量回归

- [x] 5.1 跑通 `pytest -q` 全量（新增基本工具测试 + 既有工具系统回归全绿）。
- [x] 5.2 写一个 mock 冒烟片段（tests 或说明）：用 tmp 文件展示
  `register_builtins` → `dispatch` 读文件的最小闭环可运行（可选，不强求真实端点）。