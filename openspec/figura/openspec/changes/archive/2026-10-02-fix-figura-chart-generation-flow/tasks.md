## 1. DeepSeek continuation 归一化

- [x] 1.1 扩展现有 continuation 内容类型为 `str | None`，区分对象缺失与对象内容为空；保持字段集合及 format/schema version，不放宽 Qwen/MiMo 规则。
- [x] 1.2 修正 DeepSeek 非流式归一化实际字段存在性判断，覆盖 Mapping、SDK extra/字段集合及未设置默认值；拒绝非字符串非 null 值。
- [x] 1.3 修正 DeepSeek 流式归一化，覆盖 missing、null-only、empty、nonempty、混合 null/字符串片段及非法类型。
- [x] 1.4 更新请求校验和 payload 序列化，显式 null/空字符串按原值回传；真正缺失仍拒绝，不伪造 reasoning 或改变 thinking。

## 2. Runtime 持久化和迁移

- [x] 2.1 对齐 Coordinator、continuation codec、存储映射和读取校验，保持所有权、原子提交、512 KiB 字符串上限及私有边界；移除过时的统一非空判断。
- [x] 2.2 实现 SQLite schema 9 新建与支持旧版本升级，保留现有事实、响应关联、索引、外键和不可变/Session 删除触发器；仅 DeepSeek 允许 NULL 和空串。
- [x] 2.3 使用临时数据库覆盖 schema 8 带事实迁移、已有更早版本升级、新建、失败回滚、重启读取和 Session purge；验证不填补历史缺失 continuation。
- [x] 2.4 覆盖当前及之前 Run 的逐条 assistant continuation 回放，保证实际 null、空字符串、非空值经提交、重启和请求重建后不变；验证 Qwen/MiMo 和隐私回归。

## 3. 安全的本地预检失败原因

- [x] 3.1 在 prepare 异常分支建立有界受信原因映射，已知 Provider 校验拒绝使用具体安全中文文案，未知异常保持通用文案；禁止直接持久化原始异常文本。
- [x] 3.2 将文案经 Coordinator 和 terminal repository 写入已有 `terminal_message`，保持 `execution_failed`、256 UTF-8 字节边界、CAS 和终止事务，不新增 attempt 或事件字段。
- [x] 3.3 覆盖缺失 continuation 失败、含敏感文本的未知异常、终止写入失败/冲突及 Gateway 既有 `terminalMessage` 投影；断言 prepare 失败没有网络 dispatch。

## 4. 装配说明和固定画布布局

- [x] 4.1 补充实际装配工具及 schema 字段描述中的 pie category/value、series/axes 约束与多个子图示例，保持字段集合和现有语义校验；覆盖首次拒绝后修正成功。
- [x] 4.2 在现有 renderer 中统一总标题、子标题、绘图区和 source/note 布局，先按可用宽度换行并预留文字区域，字体设置在创建对象前生效。
- [x] 4.3 给 pie 添加默认一位小数百分比，保持类别与源数据；覆盖零值、极小值、独立舍入和密集标签，无法容纳时使用有界失败。
- [x] 4.4 覆盖 1/2/3/4 子图、合法 1/2 列、有无总标题、四种图表和长中文标题/备注；断言文字位置与尺寸上限、合法 PNG、结果字段、digest 和本地幂等回放。
- [x] 4.5 查看临时生成的代表性 PNG，确认两个饼图和混合四图的标题、备注、百分比没有重叠或裁切，记录实际视觉结果。

## 5. 完整链路和回归验收

- [x] 5.1 使用临时数据和可控 DeepSeek 响应重建跨 Run 测量 → 饼图错误装配 → 修正 → 渲染 → 图像回看 → 最终答复；分别覆盖显式 null、空串和非空 continuation 的继续执行。
- [x] 5.2 对相同链路的真正 missing 分支断言安全失败、既有渲染仍可读取、没有后续 attempt/dispatch 或虚构最终答复；不触碰用户真实 Session 数据。
- [x] 5.3 用 `conda run -n agent python -m pytest -q` 先执行受影响的 Figura Provider、Runtime、Agent、装配、渲染、存储及 Gateway 定向文件，再运行完整套件；如有失败记录实际原因和范围，不以离线 mock 代替真实服务端验证结论。
- [x] 5.4 执行 `git diff --check` 与 `openspec validate fix-figura-chart-generation-flow --store figura --strict`，核对修改范围、无兼容层/额外业务字段/旧 chartagent 改动，更新任务实际状态与验收结果。


## 验收记录（2026-10-02）

- 定向回归：Provider、Runtime core、durable tool execution、Provider attempt、Agent、完整生成链路、装配工具、渲染、渲染存储、Figure state 和 Figura Gateway 共 **266 passed**，使用 `conda run -n agent python -m pytest -q` 执行上述对应文件。
- 完整回归：`conda run -n agent python -m pytest -q --tb=short`，**1023 passed / 8 failed**。8 个失败全部位于旧 `tests/test_gateway.py`：Agent service unavailable 或 HTTP 503 而非预期 202，与此前完整回归中旧 chartagent Gateway 的就绪失败范围一致；本次 Figura 测试没有失败。未修改旧实现或借此扩张配置范围。
- 已查看 `/tmp/figura-generation-visual/pies.png`（1280×522）和 `mixed.png`（1280×1002）：总标题、子标题、source/note 完整可见且无重叠或裁切，饼图显示类别及一位小数百分比。位置回归另外覆盖无总标题、长中文、1–4 子图与合法列数，无法容纳文本和密集饼图标签返回失败。
- `openspec validate fix-figura-chart-generation-flow --store figura --strict` 和 `git diff --check` 通过。
- 所有迁移、工具和集成用例均使用临时数据库及附件；没有对真实用户 `.figura` 进行迁移或补写。未请求真实 DeepSeek 服务，显式 null 的真实服务端接受行为尚未通过联网请求验证。
- 此处仅记录实施任务与验收事实；主规格、全局 overview、归档和 Git 提交未自动执行。
