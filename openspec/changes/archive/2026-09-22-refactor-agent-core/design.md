## Context

See `proposal.md` for motivation. 当前核心依赖方向大致为：

```text
Agent loop
  ├─ Measurement（范围、证据、质量、会话、门禁混在一个模块）
  ├─ Review manager（模型、策略、安全审核、候选生命周期混在一个模块）
  ├─ panel / attachment / memory
  └─ tools / model client / trace / recovery callbacks
```

`agent/loop.py` 的 `Agent.run()` 同时承担模型轮次、工具调用、恢复工作单元、panel 路由、测量状态、审核阻塞和 artifact 投影。`measurement.py` 是一个被 Agent、Review 和图表 specification 共同依赖的单文件领域模块。Review 虽然已经存在 `models.py`、`policy.py`、`evaluator.py` 和 `evidence.py`，但这些文件主要从 `manager.py` 重导出，实际所有权没有迁移。

本次迁移必须保持 JSON 状态格式、事件顺序、工具参数和包级公共导入稳定。项目没有持久化 Python 对象实例，Measurement 和 Review 的持久化边界均为字典/JSON，因此可以移动类定义，但必须保持序列化字段和语义不变。

## Goals / Non-Goals

**Goals:**

- 让 Review、Measurement 和 Agent orchestration 各自具有单一、可识别的实现所有者。
- 删除已确认不在动态注册、字符串反射、生产代码、测试或文档中使用的旧私有路径。
- 通过稳定的包级 façade 保持现有调用方兼容，并用结构测试验证实现所有权和依赖方向。
- 让 `Agent.run()` 主要表达控制流，把可独立测试的准备、路由、状态转换和投影逻辑下沉。
- 采用分阶段迁移，使每个领域完成后都能运行窄测试，最后再执行完整回归。

**Non-Goals:**

- 不修改测量质量规则、审核策略、VLM 提示词、重试预算或主 Agent 决策权限。
- 不修改 checkpoint、measurement session、review result、trace event 或 generated artifact 的持久化结构。
- 不拆分 Gateway、Evaluation、前端或图表传感器算法实现。
- 不以减少行数为唯一目标，也不创建只有一行重导出的新“分层”模块。
- 不在本 change 中移除已从 `chartagent`、`chartagent.measurement` 或 `chartagent.review` 包级公开导出的兼容符号；若确认某个公开符号应废弃，只记录后续清理项。

## Decisions

### 1. 先定义兼容边界，再删除代码

实现前建立符号清单，将候选项分为：

1. **稳定包级 API**：根包或领域包 `__init__.py` 公开导出的符号。本 change 保持导入路径、函数签名和序列化语义。
2. **内部模块 API**：仅在 `src/` 与测试内部使用的子模块符号。允许迁移，但调用点必须一次性更新。
3. **私有遗留实现**：私有名称且无静态调用、无动态注册、无文档承诺。由引用搜索和针对性测试确认后删除。

例如旧的 Review 传感器比较辅助函数已经不参与 `review_candidate_bytes()` 或 `ChartReviewManager.process()`，可作为私有遗留实现删除；`MeasurementReviewAdapter` 当前虽未被主流程实例化，但仍由 `chartagent.review` 公开导出，因此本 change 保持兼容，不把它当作可直接删除的垃圾代码。

备选方案是按照“仓库内无调用”批量删除。该方案会误删潜在外部导入和兼容入口，因此不采用。

### 2. Review 子模块成为真实实现所有者

目标布局：

```text
review/
├── models.py       # 状态枚举、Issue/Result/Candidate 等值对象
├── policy.py       # ReviewPolicy、默认限制和策略选择
├── evaluator.py    # PNG/结构安全审核及审核结果合并
├── manager.py      # 候选创建、状态迁移、发布门禁和生命周期
├── adapters.py     # shared review gate 适配器
├── gates.py        # 现有通用审核基础设施
└── vlm.py          # 现有 VLM 审核边界
```

`manager.py` 只依赖 `models`、`policy` 和 `evaluator`，这些下层模块不得反向导入 manager。当前重复导出 `review_candidate_bytes` 的 `evidence.py` 不再被视为独立领域层：若没有真实证据职责则删除该内部子模块并更新结构测试；包级 `chartagent.review.review_candidate_bytes` 继续从 canonical evaluator 导出。

`models.py` 可以通过前置类型注解引用 `ReviewPolicy`，避免 value objects 与 policy 的循环导入。共享序列化边界常量由实际使用它们的下层模块拥有，再由包级 façade 兼容导出。

备选方案是保留 manager 为实现中心、继续增加重导出文件。它不能降低耦合或测试范围，因此不采用。

### 3. Measurement 从单文件迁移为同名兼容包

目标布局：

```text
measurement/
├── __init__.py     # 保持原有公开符号集合
├── evidence.py     # evidence ref 规范化、构造和边界裁剪
├── scope.py        # MeasurementTarget、ObservationScope、fingerprint
├── quality.py      # audit、quality envelope、repair suggestion
└── lifecycle.py    # Attempt、Session、state conversion、register、gate
```

依赖方向固定为：

```text
evidence ─┐
scope ────┼──▶ quality ─▶ lifecycle
          └──────────────▶ lifecycle
```

`__init__.py` 只提供显式、稳定的公共导出，不承载业务实现。内部公共辅助函数应放入拥有其语义的模块；仅在多个模块真正共享时才建立小型内部 helper，避免生成新的通用杂物文件。

Python 无法同时保留 `measurement.py` 与 `measurement/`，因此迁移以一次原子文件替换完成：先准备子模块和包级导出，在同一实现步骤中删除旧文件并更新内部导入，然后立即运行 measurement、specification、review 和 recovery 相关测试。

备选方案是保留 `measurement.py` 作为 shim 并创建另一个命名的包。它会制造两个权威入口并延长迁移期，因此不采用。

### 4. Agent 使用单向协作者，loop 保持唯一公共编排入口

目标布局允许根据实现耦合度微调文件名，但职责边界固定：

```text
agent/
├── loop.py              # Agent 公共入口和顶层 while/turn 编排
├── turn.py              # 单轮模型结果与工具调用执行
├── recovery.py          # work unit、checkpoint、中断和恢复状态
├── measurement_flow.py  # 测量上下文、会话登记和决策事件
├── panel_routing.py     # panel 上下文恢复、选择和参数准备
└── artifacts.py         # visual observation 与 artifact 投影
```

新模块不得导入 `Agent`。`loop.py` 创建或调用协作者，并显式传入 registry、memory、callbacks、run context 等依赖；协作者返回有类型或有明确结构的结果，不直接修改 Agent 的任意字段。这样可以避免把巨型类拆成多个相互回调的巨型类。

迁移顺序从纯函数和状态投影开始，再迁移 panel/measurement 流程，最后抽取 turn/recovery。`Agent.run()` 继续拥有顶层顺序和退出语义，确保模型调用、工具 trace、checkpoint、审核阻塞及最终回答的可观察顺序不变。

备选方案是把 `Agent.run()` 直接整体移动到新类。它只会转移巨型函数并增加间接层，因此不采用。

### 5. 结构测试验证所有权，而不锁死历史文件矩阵

调整 `test_structure_compatibility.py`：

- 验证包级公共符号仍能导入且指向 canonical 定义。
- 验证 `models`、`policy`、`evaluator` 不从 manager 反向重导出。
- 验证 Measurement 包级 façade 与 canonical 子模块对象一致。
- 验证下层 Agent 协作者不导入 `agent.loop.Agent`。
- 删除仅用于保护无真实职责空壳模块的模块清单项。

行为测试仍是主要回归依据，结构测试只保护有意的依赖边界，不以文件名数量作为架构质量指标。

## Risks / Trade-offs

- **[Risk]** 大量内部导入调整可能产生循环依赖或导入时副作用。→ 先确定依赖图，下层模块不导入 façade/manager/Agent；每完成一个领域立即运行 import smoke 和窄测试。
- **[Risk]** 移动 dataclass 定义可能影响依赖具体 `__module__` 的调用方。→ 项目持久化仅使用 JSON；包级导入保持稳定，并增加 identity/serialization 回归测试。若发现真实 `__module__` 依赖，则保留兼容别名并记录后续迁移。
- **[Risk]** 删除静态无引用代码时遗漏动态调用。→ 同时检查工具 registry、字符串名称、`__all__`、文档和测试；公开导出不在本 change 中删除。
- **[Risk]** 拆分 `Agent.run()` 改变事件、checkpoint 或审核时序。→ 迁移只提取现有逻辑，不重新排序；用 trace、interrupt/resume、panel routing、measurement 和 generated review 测试固定顺序。
- **[Trade-off]** 为保持兼容，少量当前未使用的公开入口仍会保留。→ 本 change 优先获得清晰所有权和低风险迁移；真正的 breaking API 收缩另立 change。
- **[Trade-off]** 一个 change 同时涉及三个核心区域。→ 它们位于同一依赖链，按 Review、Measurement、Agent 三个可验证阶段实施，每阶段保持可回滚。

## Migration Plan

1. 记录稳定导出、内部调用和死代码候选，补充兼容/序列化基线测试。
2. 删除已确认失效的 Review 和 Agent 私有路径，并完成 Review canonical ownership 迁移。
3. 将 Measurement 原子迁移为同名包，更新内部导入并运行领域回归。
4. 按 artifacts、panel routing、measurement flow、recovery、turn 的顺序从 `Agent.run()` 提取职责，每一步运行对应窄测试。
5. 更新结构测试、模块说明和必要的开发文档；运行完整 Python 测试、图表理解 smoke、`git diff --check` 和旧引用搜索。

回滚按阶段进行：Review、Measurement 和 Agent 提取分别保持独立提交边界。若某阶段出现无法快速定位的行为差异，只回滚该阶段，不恢复已经验证完成的前置阶段。
