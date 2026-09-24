## 1. 固定新契约与数据边界

- [x] 1.1 清点 Agent、Gateway、Memory、review、前端和评测对 checkpoint、operation、candidate、review、publication、gate 的生产者及消费者，记录删除清单与仍需保留的 Run/SSE 字段。
- [x] 1.2 固定执行记录、`next_action`、暂存图、验证结果和发布 artifact 的版本化 schema、大小上限、私有/公开字段及稳定 work key；为新空库建立 schema 初始化与测试夹具。
- [x] 1.3 在同一 SQLite 写入边界中实现执行 entry、checkpoint 游标及关联公开事件的原子提交；验证部分写入失败时三者均不可见。

## 2. 收敛执行与恢复

- [x] 2.1 将 Agent 模型响应、工具结果和最终回答写入私有有序执行记录，由已提交前缀重建模型上下文，阻止 provider 私有续接内容进入会话记录、SSE、trace 和评测。
- [x] 2.2 将 checkpoint 缩为已提交游标、turn、带类型的下一动作及不可推导的安全引用；移除 messages、pending tool、measurement、review 和 gate 快照的写入及读取。
- [x] 2.3 为 `MODEL`、`TOOL`、`VERIFY`、`PROMOTE`、`FINAL` 实现匹配已提交结果复用、工具 effect 分类、稳定工作身份和顺序多工具调用恢复；同参数的有意重复调用须保持不同身份。
- [x] 2.4 实现显式子 Run resume：保留父 Run 终态和 `runId:sequence`，复用父已提交前缀与整体预算；仅显式 resume 可重发未提交模型/VLM 请求，未知外部副作用结果阻止重放。
- [x] 2.5 从 Run、checkpoint 和引用有效性推导 resumable/不可恢复原因，保持 reconnect、retry 和 resume 三种操作的语义，并用中断注入验证每个提交边界。

## 3. 实现单一生成图验证链

- [x] 3.1 将 render 输出写入受限暂存图和不可变 manifest，绑定 work key、图像/准确 ChartSpec 摘要、来源 attachment/panel/revision、generation context、figure/collection 及策略版本；实现原子文件落盘、摘要核对和孤儿清理。
- [x] 3.2 实现 session/run scoped 的来源与范围预检；过期、跨 session、摘要或 panel handoff 不匹配时返回 source-binding 诊断并关闭发布。
- [x] 3.3 执行 ChartSpec、渲染图与编码图像的确定性检查，并在源图关联或策略要求时自动执行无工具 VLM；保留四字段 JSON、六项检查、任务方式、issue 上限及失败关闭规则。
- [x] 3.4 为每次尝试提交唯一、不可变且有界的验证结论；按完整输入/策略身份复用已提交结果，并使重新生成、验证重试和跨子 Run 总预算有界。
- [x] 3.5 实现事务性、幂等的发布校验：仅匹配且策略允许的 pass/pass_with_warning 可产生正式 artifact，warning 随结果保留；失败或未决图仅能授权预览。
- [x] 3.6 将有界诊断交给主 Agent 选择合法修复动作，移除固定 repair phase；最终回答与 Run 成功终结核对未决验证、图表声明及 artifact 引用。
- [x] 3.7 验证 collection 每张子图独立的范围、尝试、issues、验证与发布结果，保留父子关联而不让通过结果覆盖失败子图。

## 4. 切换 Gateway、客户端与观察投影

- [x] 4.1 更新 Gateway 持久化、HTTP/SSE 和预览资源为暂存/验证/发布事实及派生恢复资格，保持 loopback、鉴权、脱敏、限额、Run 幂等和事件身份。
- [x] 4.2 更新 `ChartAgentClient`、`api/gatewayClient.ts`、`types/protocol.ts` 兼容外观及 Gateway/mock 两种 adapter，使新字段和事件一致；迁移所有调用者后删除旧协议字段。
- [x] 4.3 将时间线、预览、下载、warning、失败诊断、子图分组、断线补偿和终态呈现改为由已提交事实投影；重复 SSE/历史事件按同一身份合并。
- [x] 4.4 更新提示词、CLI 和评测投影，使主 Agent 获得验证事实和可选修复提示，公开输出不暴露私有执行记录或本地路径。

## 5. 删除旧状态及兼容路径

- [x] 5.1 删除通用 Operation Journal、旧 checkpoint 序列化/反序列化和其回调/工厂；逐个核实旧代码路径已被新执行记录替代。
- [x] 5.2 删除 Candidate/Review/Publication、ExecutionGate、repair phase 的运行时状态、回调、数据库表/列、Gateway 端点/事件和前端分支；不保留旧格式读取或迁移器。
- [x] 5.3 清理测试、mock、提示词、文档和评测中已废弃的状态名与假设；检查仍需保留的 ChartSpec、测量质量、来源安全及集合语义没有被删掉。
- [x] 5.4 将本 change 的 delta specs 同步到主规格，核对删除的 requirement 与新契约逐项对应，并确认主规格无相互矛盾的旧生命周期描述。

## 6. 验收与旧数据切换

- [x] 6.1 运行相关 Python 小范围回归和完整 `conda run -n agent python -m pytest -q`，覆盖提交故障、模型/VLM 未提交重发、已提交结果复用、幂等发布、来源失效和私有信息隔离。
- [x] 6.2 运行 `frontend` 的 `npm run build`、`npm run smoke`；如启动器受影响再运行 `npm run smoke:launcher`，并通过真实 Gateway 会话验证恢复、失败预览、warning、发布及集合子图。
- [x] 6.3 停止 Figura Gateway，使用与应用相同的配置解析器清点实际 `CHARTAGENT_DATA_DIR`、显式数据库/附件覆盖路径及 run-artifact 根；核对 canonical path、实例归属、可写性和删除范围。
- [x] 6.4 在验收通过后清除核对过的旧会话数据库、应用托管附件和 run artifacts（包括已发布图），不触碰外部源图、诊断/评测产物、`.env` 或无关目录。
- [x] 6.5 从新空库启动 Gateway 并完成新会话、生成图、断点恢复与历史读取验证；运行 `openspec validate simplify-run-state-and-chart-verification --strict`、旧符号清单检查及 `git diff --check`。
