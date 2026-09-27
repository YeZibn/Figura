---
name: figura-implementation-read
description: Read Figura's layered system overview and relevant component document, then verify current code and OpenSpec facts before answering architecture, model, field, flow, or next-change questions; read-only.
---

# 读取 Figura 分层系统文档

先读 `docs/figura-implementation-overview.md`，确定问题涉及的大组件和当前状态；再按**语义与权威 owner**寻找相关 `docs/figura/*.md` 专题。专题集合会随领域变化扩展，不能假定固定目录或按调用链把 Agent、Provider、Tool 当成一个领域。专题中的内部流转与完整字段表是导航，不代替代码和规格核对。用户要求维护这些文档时使用 `$figura-implementation-overview`；本 skill 只读。

## 核对顺序

1. 看 `git status --short`，识别工作树已有改动。新 Figura 的实现事实核对 `src/figura/`；字段至少看模型定义、编解码、写入/调用与读取/投影。只打开相关文件。
2. 行为合同看 `openspec/figura/openspec/specs/`；活动 change 另看对应 proposal/design/specs/tasks 和当前状态。先以 `openspec store list --json` 解析 store id，后续带 `--store <id>`。
3. `docs/figura-architecture-design.md` 是长期设计草案；`src/chartagent/` 与 chartagent store 是旧系统。只有比较、迁移或兼容性问题才作为参考，不能用来证明新 Figura 已实现。
4. 回答时分开写：当前工作树代码、主规格合同、活动设计、旧系统参考、实际运行过的验证。Overview 与代码冲突时指出文档待更新，不在只读任务中改写。

字段问题先找定义该合同的领域文档，给出完整 `Model.field` 路径、owner、写入、持久化或调用期位置、读取与公开边界；消费方文档只解释映射。流程问题说明内容穿过哪些组件及失败/恢复分支。不要把 ExecutionRecord、Checkpoint、RunStreamEvent 当成同一种事实。
