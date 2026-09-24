## 1. 建立兼容与清理基线

- [x] 1.1 盘点 `chartagent`、`chartagent.measurement` 和 `chartagent.review` 的包级导出、内部导入、字符串注册与文档引用，形成稳定 API、内部 API 和私有遗留实现清单。
- [x] 1.2 为 Review/Measurement 值对象的包级 identity、函数签名、JSON 序列化与状态 round-trip 增加基线测试，固定迁移前行为。
- [x] 1.3 用 `rg` 和运行路径检查确认旧 Review 传感器比较、旧 Agent 测量修复辅助等私有候选无调用后删除，并保留所有仍公开导出的兼容符号。

## 2. 完成 Review 领域拆分

- [x] 2.1 将 Review 状态枚举、issue/result/candidate 值对象迁移到 `review/models.py`，保持字段、默认值、序列化键和包级导出不变。
- [x] 2.2 将 `ReviewPolicy`、限制常量和策略选择迁移到 `review/policy.py`，消除 policy 对 manager 的反向依赖。
- [x] 2.3 将 PNG/结构安全审核和审核结果合并迁移到 `review/evaluator.py`，删除已被 VLM 审核取代的旧传感器比较链路。
- [x] 2.4 收缩 `review/manager.py` 为候选创建、状态迁移、发布门禁和生命周期编排，并更新 adapters、VLM review 与包级 façade 的 canonical imports。
- [x] 2.5 删除或重定向无真实职责的 Review 空壳模块，更新结构兼容测试并运行 Review、generated chart gate 和 VLM review 相关测试。

## 3. 将 Measurement 迁移为领域包

- [x] 3.1 创建 Measurement evidence 与 scope 子模块，迁移 evidence ref、target、observation scope、fingerprint 和相关边界辅助逻辑。
- [x] 3.2 创建 Measurement quality 子模块，迁移 audit、quality envelope、issue/check 和 repair suggestion 逻辑，保持现有质量结果不变。
- [x] 3.3 创建 Measurement lifecycle 子模块，迁移 attempt/session、状态转换、register 和 gate 逻辑，并保持 checkpoint JSON 兼容。
- [x] 3.4 原子地用 `measurement/` 包替换 `measurement.py`，通过显式 `__init__.py` 重导出保持所有稳定包级导入，并更新 Agent、Review 和 chart specification 的内部引用。
- [x] 3.5 增加 Measurement canonical ownership、serialization 和 import compatibility 测试，运行 measurement quality、repair、specification、checkpoint/recovery 相关测试。

## 4. 提取 Agent 的数据准备职责

- [x] 4.1 将 visual observation 引用绑定和 artifact record 投影迁移到 `agent/artifacts.py`，保持 observation 内容、引用字段和 trace 摘要不变。
- [x] 4.2 将 panel context 恢复、layout 参数准备、panel 选择与路由错误迁移到 `agent/panel_routing.py`，保持 panel handoff 和局部测量参数语义不变。
- [x] 4.3 将测量修复上下文、session 登记和 measurement decision event 迁移到 `agent/measurement_flow.py`，保持由主 Agent 自主接受、舍弃或定向补充的现有行为。
- [x] 4.4 为三个协作者补充聚焦单元测试，并运行 panel routing、dashboard decomposition、measurement flow 和 artifact observation 测试。

## 5. 收缩 Agent 主循环

- [x] 5.1 将 work unit、checkpoint payload、中断检查与 recovery tool call 恢复迁移到 `agent/recovery.py`，保持 operation 幂等性和事件顺序不变。
- [x] 5.2 将单轮模型结果处理和工具调用执行迁移到 `agent/turn.py`，通过显式依赖和返回结果与 `loop.py` 协作，禁止新模块反向导入 `Agent`。
- [x] 5.3 重写 `Agent.run()` 为顶层编排流程，复用已提取协作者，并保持最终回答、审核阻塞、工具 trace、checkpoint 和异常退出语义不变。
- [x] 5.4 增加模型轮次、工具失败、审核阻塞、中断、断点恢复和多 panel 运行的顺序回归测试，确认提取前后事件投影一致。

## 6. 结构与完整回归验证

- [x] 6.1 更新结构兼容测试，验证 canonical 定义所有权、包级 façade identity 和单向依赖，移除只保护历史空壳模块的断言。
- [x] 6.2 更新受模块布局影响的源码说明和开发文档，使用 `rg` 确认不存在旧 canonical import、失效私有符号或从下层模块反向导入 façade 的情况。
- [x] 6.3 使用 `conda run -n agent python -m pytest -q` 运行完整 Python 测试，并运行图表理解 smoke 入口确认 `rapidocr` 与工具注册链路正常。
- [x] 6.4 执行 `git diff --check` 和工作区状态审查，确认未混入 Gateway、Evaluation、前端或图表传感器算法的非预期改动。
