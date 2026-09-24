## Context

工具系统机制（add-tool-system，已归档）提供 `Tool` / `ToolRegistry` /
`dispatch`，结果统一 JSON 字符串、失败为 `{"error": ...}`。本 change 在其上
用同一机制注册一组只读基础工具，作为 agent loop 的第一份能力面。全部为纯
函数、无副作用，保证第一批工具可安全调用。

## Goals / Non-Goals

**Goals**
- 提供 4 个只读内置工具：`read_file` / `list_dir` / `parse_json` /
  `read_json_file`
- 统一注册入口 `register_builtins(registry)`，一次性批量注册
- 每个工具复用 `Tool` 定义与 `dispatch` 的 JSON 结果协议

**Non-Goals**
- 不含写/删除等副作用工具（`write_file`/`delete_file` 等留给后续 change）
- 不含数据统计（mean/sum）、文本转换类工具
- 不做路径安全性校验（路径白名单/沙箱）——本期为本地只读原语
- 不实现 agent loop（拆第二个 change）

## Decisions

**1. 全部只读，零副作用——第一批只做"读"。**
`read_file`/`list_dir`/`parse_json`/`read_json_file` 都是确定性纯函数，可被
agent 随意调用而无破坏风险。写/删等副作用工具对安全边界要求更高，延迟到
loop 有实际需求时再单独评估。
- *备选:* 第一批就含 `write_file` → 副作用工具默认不开放更稳妥，弃用。

**2. 组织：`builtin/` 子包 + 统一 `register_builtins(registry)`。**
按域分模块：`files.py`（read_file/list_dir）、`data.py`（parse_json/
read_json_file）、`register.py` 提供 `register_builtins()`。调用方只需一次
注册拿到完整 registry，后续 loop / MCP converter 都只面对这一个 registry。
- *备选:* 所有工具堆在一个模块 → 无结构，弃用；拆到工具系统机制层 →
  本层是"工具实例"不是"机制"，应放 builtin 扩展目录。

**3. 失败路径统一走 `{"error": ...}`，不预称异常。**
每个工具内部捕获 IO/JSON 异常并以结构化错误返回，从而直接穿过 `dispatch`
的既有控制流，不用依赖 dispatch 兜底。这样 LLM 能读到同一形状的错误。
- *备选:* 让异常冒泡交给 dispatch 统一捕获 → 也能工作，但工具自身先归一
  化错误信息更可读，采用前者。

**4. `read_json_file` = 组合原语，不复写解析逻辑。**
实现上读文件后调用 `parse_json` 的解析函数，保持单点解析逻辑，避免重复。
- *备选:* 独立实现一遍 json.load → 重复且易不一致，弃用。

## Risks / Trade-offs

- [路径任意可读，无沙箱限制] → 本期定位为本地原语、纯只读、无破坏面；若未来
  暴露给外部宿主或需限定目录，再补路径白名单（属工具系统的安全扩展）。
- [工具少（仅 4 个）] → 有意为之，先立住"读"半边；写/统计/文本按需在后续
  change 补齐，避免堆数量无意义。

## Migration Plan

无存量系统需迁移；本 change 纯新增工具注册模块。无回滚负担。

## Open Questions

无。范围（4 个只读工具 + 统一注册入口，不含副作用/loop）已明确，可安全实施。