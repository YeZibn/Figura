<p align="center">
  <img src="docs/assets/figura-logo.png" alt="Figura 图标" width="180" />
</p>

<h1 align="center">Figura</h1>

<p align="center">
  <strong>由图见数，由数见意。</strong><br />
  <sub>从像素中辨认脉络，循证据还原其数，于理解之后，重构其形。</sub>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#设计立场">设计立场</a> ·
  <a href="#工作原理">工作原理</a>
</p>

Figura 是一个面向图表理解与重绘的本地工作区。你可以把图像带进对话，要求 Agent 识别结构、提取文字、测量数据、解释观察中的不确定性，再把分析结果组织成可预览和下载的图表。运行事实、图像资源与工具过程由本地工作区管理；模型推理由你配置的远端 Provider 执行。

本文介绍 `src/figura/` 当前实现及其使用方式。

## 设计立场

> 一张图表不是结论的终点，而是理解的起点。

图表不是原始数据，也不会自动给出可靠结论。它是一种视觉编码：读者要从像素中辨认刻度、颜色、类别和几何关系，再把观察转化为推断。Figura 不把观察、判断和表达压成一个不可拆分的答案，而是尽量保留它们之间的边界，让用户可以继续追问，也能看见结论从何而来。

- **观察先于结论。** OCR 和测量提供候选证据，而非无条件正确的答案。轴标定不足时，Figura 保留像素位置和警告，不用看似精确的数字遮住不确定性。
- **模型负责选择，工具负责兑现。** Agent 决定接下来要观察什么；工具校验输入、范围和结果，并把执行写成可检查的事实。用户可以沿着运行过程理解分析，而无需先掌握内部调度细节。
- **摘要帮助继续工作，历史负责保存来路。** 长对话摘要用于快速找回目标、决定和待办；它不会替换原始运行事实，历史资源仍可按引用检索。
- **重绘也是一种理解。** 把读到的数据组织成另一种图表，是对结构和关系的再次表达。新图表是分析产物，仍需要依据输入数据与图表规格进行校验。

## 当前可以做什么

| 能力 | 当前行为 |
| --- | --- |
| 图表阅读 | 按需加载原图，结合视觉理解、OCR 和测量回答标题、单位、类别、趋势与数值问题 |
| 多图分析 | 根据模型提出的多边形区域，把仪表盘或拼图拆成命名 Panel，分别观察与测量 |
| 图像观察 | OCR 与统一图表测量共享可见像素解码；透明像素与临时 include/exclude 区域共同决定本次检测范围，不改变原图和坐标系 |
| 图表测量 | 支持柱状图、折线图、散点/气泡图、饼图/甜甜圈图、面积图、直方图、箱线图、雷达图、热力图与矩形树图；按证据质量返回标定数据、像素位置、警告或不支持状态 |
| 图表生成 | 从用户提供的数据或图像分析结果组装 `ChartFigure`，支持单图和多图画布，生成 PNG |
| 会话工作区 | 创建、切换和删除会话，上传及预览附件，查看分区图像、分析回答与生成图，下载 PNG |
| 过程查看 | 按 Run 展示工具时间线，按需展开参数与结果摘要，并查看成功 OCR／测量的观察图 |
| 历史取回 | 可按文本与来源过滤历史，再读取原消息、工具结果、完整 Figure 或类型化图像资源；读取不会重放旧工具 |
| 上下文管理 | 本地估算输入占比；达到已配置窗口阈值时可生成有来源引用的分层摘要，旧事实仍可检索 |
| 停止与恢复 | 可请求协作停止；Gateway 启动和运行期间会恢复持久化 Run，未知执行结果不会被盲目重放 |
| Provider 重试 | 对已确认且分类为临时的网络或服务失败自动重试；每个逻辑模型请求最多四次物理尝试 |
| 持久化与对话 | SQLite 保存输入、模型与工具执行事实、checkpoint、摘要检查点和事件；后续 Run 从同一会话的已提交事实重建对话 |
| 模型接入 | 在网页中选择已配置的 Qwen、DeepSeek 或 MiMo；模型 ID 由后端固定 |

测量工具返回的是候选观察。轴标定不足时会保留像素信息与警告，不能把这些结果直接当作精确数据。透明图像在检测时先按白底合成；透明隐藏色不会作为证据，OCR 跨出有效可见区域的文字框会被舍弃。当前生成图经过结构和语义校验并可由 Agent 回看；通用证据生命周期、独立的生成图验证、发布和新 Figura 评测链尚未实现。

## 快速开始

### 1. 准备运行环境

从仓库根目录执行以下命令。Python 命令统一使用名为 `agent` 的 Conda 环境；已有该环境时跳过创建步骤。

```bash
conda create -n agent python=3.11 -y
conda run -n agent python -m pip install -e '.[dev]'
npm --prefix frontend install
```

后端声明支持 Python 3.10 及以上。前端启动脚本使用 `import.meta.dirname`，可使用 Node.js 22 及以上版本。当前 Run 执行锁依赖 `fcntl`，后端应在 macOS 或 Linux 上运行。

主要依赖包括 React、TypeScript、Vite、OpenAI Python SDK、RapidOCR、Pillow、NumPy 和 Matplotlib，完整清单见 [pyproject.toml](pyproject.toml) 与 [frontend/package.json](frontend/package.json)。

### 2. 配置模型

如果还没有 `.env`，复制配置模板：

```bash
cp .env.example .env
```

至少配置一个 Figura Provider。例如，使用 DeepSeek 时填写：

```dotenv
FIGURA_DEEPSEEK_API_KEY=your_api_key
FIGURA_DEEPSEEK_BASE_URL=https://api.deepseek.com
FIGURA_DEEPSEEK_TIMEOUT_SECONDS=60
FIGURA_DEEPSEEK_THINKING_MODE=true
```

Figura 的模型配置使用 `FIGURA_*` 环境变量。至少配置一个 Provider 后，网页才会显示对应的模型选项。

| Provider | 当前固定模型 ID | 必填配置 | Endpoint 配置 |
| --- | --- | --- | --- |
| Qwen | `qwen3.8-flash` | `FIGURA_QWEN_API_KEY`、`FIGURA_QWEN_BASE_URL` | 无默认地址；填写与 API key 所属区域及工作空间匹配的 OpenAI 兼容地址 |
| DeepSeek | `deepseek-flash` | `FIGURA_DEEPSEEK_API_KEY` | `FIGURA_DEEPSEEK_BASE_URL`，默认 `https://api.deepseek.com` |
| MiMo | `mimo-v2.6-flash` | `FIGURA_MIMO_API_KEY` | `FIGURA_MIMO_BASE_URL`，默认 `https://api.xiaomimimo.com/v1`；使用其他套餐时同时配置匹配的地址和 key |

各 Provider 可设置 `FIGURA_<PROVIDER>_TIMEOUT_SECONDS` 和 `FIGURA_<PROVIDER>_THINKING_MODE`，默认分别为 `60` 和 `true`。还可按 Provider 设置 `FIGURA_<PROVIDER>_MAX_COMPLETION_TOKENS`；它只配置单次模型请求的输出上限，不形成 Run 累计预算。Qwen、DeepSeek 还可配置 `REASONING_EFFORT`，具体取值见 [.env.example](.env.example)。网页按本地配置显示可用 Provider；这个检查不会验证远端连通性、额度或请求是否能成功。

#### 可选：显示上下文占比

Figura 对所有 Provider 统一使用 `tiktoken/o200k_base` 估算最近一次模型请求的输入 token。准备编码缓存后重启服务：

```bash
conda run -n agent python -c "from dotenv import load_dotenv; load_dotenv('.env', override=False); import tiktoken; tiktoken.get_encoding('o200k_base')"
```

此准备步骤首次需要下载公开编码资源，运行期估算不访问网络。`.env.example` 将 `TIKTOKEN_CACHE_DIR` 配置为 `${HOME}/.cache/figura/tiktoken` 持久目录；准备命令读取项目 `.env` 后会使用同一路径。未配置时仍回退到系统临时目录。缓存缺失、损坏或被禁用时，模型调用仍继续，输入区显示“上下文待估算”；准备缓存后需重启服务。

`.env.example` 已为当前固定的 Qwen、DeepSeek、MiMo 模型填写 1,000,000 tokens 的上下文容量；对应依据见 [Qwen 模型信息](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)、[DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 和 [MiMo 模型列表](https://mimo.mi.com/docs/zh-CN/quick-start/summary/model)。若使用不同模型部署或服务合同，需按实际容量调整对应的 `FIGURA_<PROVIDER>_CONTEXT_WINDOW_TOKENS`。没有有效容量时只显示估算 token 数，不猜测模型窗口。

计数包括实际发送的指令、工具定义、历史、工具参数/结果与回放 continuation。每次出现的图片按 1,024 tokens 近似，不计算 base64 文本。输入区的“上下文 ≈”对应最近请求；不累计多次调用，不计算草稿或正在生成的回复。点击指示器可查看数量、原请求模型与说明。重试复用同一估算，超过 100% 也不会在本地阻止发送。

#### 自动摘要与历史取回

仅当所选 Provider/model 配置了有效上下文容量、估算可用且最近请求达到约 80% 时，Agent 才考虑对较早的完整历史额外调用一次模型生成摘要。该请求使用独立的 `src/figura/agent/prompting/assets/compaction.md`，只发送摘要指令和授权历史文本，不附工具或图像。摘要将当前目标、约束、决定、事实、完成／进行中／待办／阻塞、未决问题、资源和未接受提议分开记录；每条内容都带有授权历史来源引用。摘要只是 Runtime 保存的派生检查点，不替换或删除原始 Run 事实。

容量未知或估算不可用时不会自动触发摘要。摘要请求失败、格式或来源校验失败时，既有检查点保持不变，请求回退到完整历史路径。上下文占比不限制模型调用，也不会自动截短用户输入、工具结果或历史；即使估算超过 100%，Provider 仍可能接受或拒绝该请求。

模型还可以使用三个只读历史工具：`search_history` 按大小写无关的文本匹配和过滤条件查找引用，不承诺语义搜索；`read_history` 按精确引用读取原消息、工具结果／错误、异常调用状态或完整结构化资源；`read_resource_image` 只接受已授权的图像资源引用。完整 `ChartFigure` 通过 `read_history` 读取；要视觉检查它，必须显式调用渲染工具或读取已经存在的 `ChartRender`。图像必须显式请求，搜索到资源或摘要中出现引用不会自动把图片加入下一次模型请求。

估算快照与具体 Provider 请求绑定，重试沿用同一请求身份和估算结果。摘要检查点由 Runtime 持久化，不新增独立历史副本。更细的请求投影、恢复和持久字段见 [Agent](docs/figura/agent.md)、[Runtime](docs/figura/runtime.md) 与 [Memory](docs/figura/memory.md)。

### 3. 启动 Figura

```bash
npm --prefix frontend run dev:figura
```

打开 [Figura 浏览器工作区](http://127.0.0.1:1421/)。默认地址为：

| 服务 | 地址 |
| --- | --- |
| React / Vite | `http://127.0.0.1:1421` |
| Figura Gateway | `http://127.0.0.1:8766` |
| 健康检查 | `http://127.0.0.1:8766/api/v1/health` |

启动器先等待 Gateway 就绪，再启动 Vite。按 **Ctrl-C** 会停止它创建的进程组；不要在相同端口启动多个实例。这个入口运行浏览器工作区，无需 Rust 或 Tauri。

Gateway 加载仓库根目录的 `.env`，已有进程环境变量优先。修改 Provider 配置后，重启启动器。

## 使用方式

1. 创建会话，选择一个可用 Provider。
2. 分析图片时上传附件，并选中要用于本次消息的图片；直接绘图时可在消息中提供数据。
3. 用自然语言说明希望得到的结果。Agent 会按任务选择工具，不要求每次都执行 OCR、分图或测量。
4. 查看回答和 Run 工具时间线。成功分割的 Panel、观察图与生成图可按需预览，生成图可下载为 PNG。
5. 在同一会话继续提问，引用先前图像或已生成图表。每个会话同时最多运行一个 Run。

可尝试以下请求：

```text
这张图展示了什么？说明横纵轴、单位和主要趋势，不确定的数值请标出来。

把这张仪表盘中的图表分开，分别说明结论，再比较它们的共同趋势。

尽量读取柱状图各类别的数值；如果无法可靠标定坐标轴，请说明限制。

根据以下数据生成柱状图：一月 12，二月 18，三月 15。标题为“季度销量”。

把刚才的数据同时画成柱状图和折线图，放在同一张画布中。
```

支持上传 PNG、JPEG、GIF 和 WebP。上传时图片先保存到本地；Agent 调用 `load_image` 等需要图像回看的工具后，相关图片才会进入所选 Provider 的模型请求。运行、附件和图表文件保存在本机，模型推理仍需要访问配置的远端服务。

已被 Run 引用的附件不能单独删除。会话删除需要网页确认，且会话必须没有运行中的 Run；删除会同时清理该会话的执行事实、附件、Panel 和渲染文件。

## 工作原理

Figura 将模型决策、工具执行、持久化和浏览器展示分别交给明确的组件。

```mermaid
flowchart LR
    UI[浏览器工作区] -->|HTTP / SSE| Gateway[本地 Gateway]
    Gateway --> Runtime[Runtime: Session / Run / Facts / Checkpoints]
    Gateway --> Sources[Sources: 附件 / Panel / PNG]
    Gateway -->|异步调度| Agent[Agent: 模型与工具循环]
    Runtime -->|已提交事实| Agent
    Sources -->|资源与图像| Agent
    Agent -->|历史搜索与精确读取| Tools
    Tools --> Memory[Memory: 规范历史与来源引用]
    Memory --> Tools
    Memory -->|规范消息与历史快照| Agent
    Agent <--> Provider[Provider: Qwen / DeepSeek / MiMo]
    Agent --> Tools[Tools: 图像 / OCR / 测量 / 绘图]
    Tools --> Charts[Charts: 校验与 PNG 绘制]
    Tools --> Sources
    Agent -->|提交结果与进度| Runtime
    Runtime --> DB[(SQLite)]
    Sources --> DB
    Sources --> Files[(本地私有图片文件)]
```

- **Session 与 Run**：Session 是会话和资源归属边界，一次用户提交创建一个 Run。Run 输入、执行事实与 checkpoint 持久化；HTTP 重复提交通过幂等键复用原 Run。
- **Agent 与提示**：Agent 运行模型—工具循环。普通请求由稳定行为规则、当前工具目录和 Run 资源／执行索引组成三层基础指令；使用摘要时还会加入一层摘要索引。专用摘要资产 `src/figura/agent/prompting/assets/compaction.md` 不进入普通回答指令。
- **Memory 与资源目录**：后续 Run 从同会话较早终态 Run 的事实重建 user、assistant 和 tool 消息。Agent 的 `RunExecutionState` 是服务端调用期目录，按授权事实索引 Attachment、Panel、OCR、Measurement、ChartFigure 和 ChartRender；完整内容不是独立持久化副本，提示只投影当前相关索引。原始 Run 事实和 Sources 文件仍是权威来源。
- **历史检索**：`search_history` 与 `read_history` 读取经授权的消息、工具结果、异常状态和资源元数据；`read_resource_image` 显式读取允许的图像。检索工具只读，不会重放历史工具调用。
- **工具与图表**：工具按版本化 Schema 校验输入和结果。`ChartSpecData` 描述单图，`ChartFigure` 描述多图画布；组装成功后，渲染工具使用已提交 Figure 生成 PNG。
- **网页与事件**：SSE 通知生命周期和进度变化，前端重新读取安全摘要。工具详情、观察图和 PNG 按需加载；事件流不复制完整工具 payload。

### 当前工具

Gateway 当前注册的工具目录版本为 `figura-web-v9`，共 9 个模型可调用工具。图表测量使用要求显式 `chart_type` 的 `measure_chart`；Agent 负责选择图表家族，工具不做隐藏分类或自动切换。名称、中文说明与参数 Schema 来自同一 Registry；具体输入输出和恢复语义见 [Tools 文档](docs/figura/tools.md)。

| 工具 | 用途 |
| --- | --- |
| `load_image` | 加载被授权的附件或 Panel，供模型在下一轮观察 |
| `decompose_chart_image` | 按模型提出的规范化多边形分割附件，保存命名 Panel |
| `search_history` | 按文本、Run 和来源类型搜索已授权的历史并返回短摘录与引用 |
| `read_history` | 按引用读取原消息、工具结果、异常状态或完整资源内容 |
| `read_resource_image` | 按专用类型化引用显式加载附件、Panel、成功观察图或 ChartRender |
| `extract_text` | 独立 OCR，返回文字、位置与置信度 |
| `measure_chart` | 按显式选择的家族观察十类图表；气泡图归入散点图，甜甜圈图归入饼图 |
| `assemble_chart_figure` | 解析和校验画布及各图的 ChartSpec，可引用同会话成功测量调用 |
| `render_chart_figure` | 渲染已提交的 ChartFigure，保存并返回 PNG 元数据 |

OCR 和测量共享可见像素解码：有效像素是图像自身可见区域与请求的 include/exclude 多边形共同作用的结果；透明像素按白底合成，隐藏 RGB 不参与检测。工具保留原图尺寸和坐标系，空观察范围会明确失败。十个家族分别返回封闭的类型化观察分支；测量引用只证明对应成功工具调用存在，不能证明画布中填写的数据与测量值一致。ChartSpec 与 ChartFigure 使用 v2 合同，不转换旧版内容；旧 Run 原始事实保留，但不投影成 v2 图表资源。工具完整输入输出和恢复策略见 [Tools 文档](docs/figura/tools.md)。

### 恢复边界

Gateway 在启动和运行期间会扫描并恢复持久化的 running Run。已提交结果可以复用；安全且幂等的工具可按原调用身份恢复。

已确认的临时 Provider 失败会在同一个持久请求绑定下自动重试，最多四次物理尝试（含首次）；SDK／HTTP 客户端的隐藏重试已关闭。认证、额度耗尽、无效请求和无法分类的失败不会自动重试。没有确定响应的请求通常保持结果未知，不会盲目再次发送；只有满足严格条件的纯生成请求才可能在旧执行 owner 已退出后替换尝试。工具失败不会由通用工具层自动重复执行，模型可根据已知结果决定下一步。副作用不明的调用不会被盲目重放。

网页提供“停止分析”操作。它会记录协作停止请求，让当前已开始的步骤有机会提交结果，再由 Agent 在安全边界结束；如果正在运行的处理器没有返回，界面会继续显示等待停止。Figura 网页没有手动重试或重新打开终态 Run 的按钮；失败或中断后可在同一会话提交新消息。后续 Run 可继续使用同一会话的已提交历史，Agent 从事实重建对话、异常结果和资源目录。

不同 Provider 的原生 continuation 不会自动相互转换；切换 Provider 后，如果历史包含目标 Provider 不支持的 continuation，请求准备可能拒绝该历史。此时可继续使用原 Provider，或在新会话开始另一条对话。

Run 没有累计模型调用次数、工具调用次数、运行时长或输出 token 预算。`FIGURA_<PROVIDER>_MAX_COMPLETION_TOKENS` 可选设置的是单次模型请求上限；执行载荷、图像、并发和存储仍受各自技术保护规则约束。

## 配置与本地数据

| 配置项 | 默认值 | 作用 |
| --- | --- | --- |
| `FIGURA_DATA_DIR` | 仓库根目录下 `.figura/` | SQLite 与私有图片的统一根目录；相对路径从仓库根目录解析 |
| `FIGURA_GATEWAY_PORT` | `8766` | Gateway 端口 |
| `VITE_DEV_PORT` | `1421`（Figura 启动器） | Vite 端口 |
| `VITE_DEV_HOST` | `127.0.0.1`（Figura 启动器） | 前端 loopback 地址 |
| `FIGURA_WEB_ORIGINS` | 端口 `1421` 的本地 HTTP Origins | Gateway 浏览器来源白名单；启动器自动补入当前前端端口的 loopback Origins |
| `FIGURA_CONDA_ENV` | `agent` | 启动器使用的 Conda 环境 |
| `FIGURA_CONDA_EXECUTABLE` | `conda` | 启动器使用的 Conda 可执行程序 |
| `FIGURA_<PROVIDER>_TIMEOUT_SECONDS` | `60` | Provider 请求超时 |
| `FIGURA_<PROVIDER>_THINKING_MODE` | `true` | Provider 思考模式开关；实际支持取决于对应适配器 |
| `FIGURA_<PROVIDER>_REASONING_EFFORT` | 未设置 | Qwen、DeepSeek 可选项；取值见 `.env.example`，MiMo 不支持此项 |
| `FIGURA_<PROVIDER>_MAX_COMPLETION_TOKENS` | 未设置 | 单次请求输出 token 配置，不是 Run 总预算 |
| `FIGURA_<PROVIDER>_CONTEXT_WINDOW_TOKENS` | 未设置 | 上下文占比的显示分母；`.env.example` 为当前固定模型设置 1,000,000 |
| `TIKTOKEN_CACHE_DIR` | 系统临时缓存 | tokenizer 编码缓存目录；`.env.example` 配置为 `${HOME}/.cache/figura/tiktoken` |
| `FIGURA_EXECUTION_PAYLOAD_MAX_BYTES` | `33554432`（32 MiB） | 单个完整执行 JSON 单元的编码大小保护，不是 Run 执行预算 |

启动器端口等选项从启动进程环境读取，可这样覆盖：

```bash
FIGURA_GATEWAY_PORT=8876 VITE_DEV_PORT=1521 npm --prefix frontend run dev:figura
```

默认数据布局如下，目录按需创建：

```text
.figura/
├── figura.sqlite3     # Session、Run、执行事实、checkpoint 与来源元数据
├── attachments/      # 上传图片
├── panels/           # 分割后的独立 PNG
├── chart-renders/    # 生成图表 PNG
└── .run-locks/       # Run 独占执行锁
```

Runtime 与 Sources 共用一份 SQLite。图片字节保存在私有文件中，OCR／测量观察图按需重建；图表的完整结构和结果借用通用工具事实保存。Provider continuation 和请求恢复绑定作为私有执行数据保存，公开 DTO 不返回它们，也不返回 API key、原始 endpoint、本机文件路径或原始 Provider 响应。单张图片、图片总量和执行 JSON 均有独立技术上限；这些保护不会形成 Run 累计调用或输出预算。

`.env` 和 `.figura/` 已被 Git 忽略。备份或迁移数据时停止服务，并保留整个 `.figura/` 目录，使数据库引用与图片文件一起迁移。

## 开发与验证

### 常用命令

```bash
# 完整 Python 测试套件
conda run -n agent python -m pytest -q

# 聚焦当前 Figura 的运行、Agent 与网页边界
conda run -n agent python -m pytest -q \
  tests/test_figura_run_execution_core.py \
  tests/test_figura_agent_executor.py \
  tests/test_figura_context_compaction.py \
  tests/test_figura_history_retrieval.py \
  tests/test_figura_observation_scope.py \
  tests/test_figura_prompting.py \
  tests/test_figura_gateway.py

# 前端类型检查与生产构建
npm --prefix frontend run build

# 前端及启动器静态 smoke 检查
npm --prefix frontend run smoke

# 启动器信号处理与端口释放检查，使用隔离端口
npm --prefix frontend run smoke:launcher

# 提交前检查
git diff --check
```

前端改动需运行 build 和 smoke；启动器改动还需运行 smoke:launcher。Python 行为改动先运行对应测试文件，再运行完整测试。OCR 相关命令始终使用 `agent` 环境。

单独启动 Figura Gateway：

```bash
conda run -n agent python -m figura.gateway
```

主要 HTTP 路由位于 `/api/v1`，下表省略该前缀：

| 路由 | 用途 |
| --- | --- |
| `GET /health` | 本地配置与服务健康信息 |
| `GET /sessions`、`POST /sessions` | 列出或创建会话 |
| `GET /sessions/{sessionId}`、`DELETE /sessions/{sessionId}` | 会话快照或没有活动 Run 的会话删除 |
| `GET /sessions/{sessionId}/attachments`、`POST /sessions/{sessionId}/attachments?filename=...` | 附件列表或原始图片字节上传 |
| `GET /sessions/{sessionId}/attachments/{attachmentId}/content`、`DELETE /sessions/{sessionId}/attachments/{attachmentId}` | 授权读取附件或删除未被 Run 引用的附件 |
| `GET /sessions/{sessionId}/panels`、`GET /sessions/{sessionId}/panels/{panelId}/content` | 分区列表或 PNG 读取 |
| `POST /sessions/{sessionId}/runs` | 创建 Run，必需 `Idempotency-Key`，请求包含 `text`、`attachmentIds`、`providerId` |
| `POST /sessions/{sessionId}/runs/{runId}/stop` | 写入协作停止请求；当前动作可先提交真实结果 |
| `GET /sessions/{sessionId}/runs/{runId}/history`、`GET /sessions/{sessionId}/runs/{runId}/events` | 历史读取或 SSE，使用 `afterSequence` 游标 |
| `GET /sessions/{sessionId}/runs/{runId}/timeline` | 工具步骤摘要 |
| `GET /sessions/{sessionId}/runs/{runId}/timeline/{callId}`、`GET /sessions/{sessionId}/runs/{runId}/timeline/{callId}/observation` | 安全详情或 OCR／测量观察图 |
| `GET /sessions/{sessionId}/runs/{runId}/chart-renders/{callId}/content` | 成功渲染的图表 PNG |

Gateway 绑定 `127.0.0.1`，写请求校验明确的本地 Origin。所有资源读取都检查 Session 归属；工具执行由 Agent 驱动，没有独立网页测量或绘图操作 API。完整 HTTP 与 DTO 合同见 [Gateway 代码](src/figura/gateway/application.py)、[主规格](openspec/figura/openspec/specs/figura-web-gateway/spec.md) 和 [Web 文档](docs/figura/web.md)。

### 目录导航

```text
src/figura/
├── agent/        # ReAct 编排、请求组装、提示资产与资源目录
├── runtime/      # Session / Run、持久事实、checkpoint 与工具执行
├── providers/    # Provider 配置、适配器与归一化合同
├── tools/        # 工具注册、Schema、handler 与测量传感器
├── sources/      # 附件、Panel、渲染图像与私有文件
├── charts/       # ChartSpec / ChartFigure、校验与绘制
├── memory/       # 从 Run 事实重建会话消息
├── gateway/      # HTTP / SSE、安全投影与异步调度
├── storage/      # 共享 SQLite、事务与 schema
└── shared/       # JSON Schema 与图像限制

frontend/src/     # React 工作区、API 适配器、纯领域逻辑与共享组件
frontend/scripts/ # 开发启动器与 smoke 检查
tests/            # Python 测试与图表 fixtures
docs/figura/      # 当前 Figura 的领域文档
openspec/figura/openspec/ # 当前 Figura 主规格与变更归档
```

## 常见问题

**Provider 不可用或创建 Run 失败**

确认填写的是 `FIGURA_*` 配置；Qwen 需要显式填写 BASE_URL。修改后重启服务。health 只做本地配置检查，远端认证、网络或模型请求失败仍会在运行时出现。

**提示 `No module named 'rapidocr'`**

先核对运行环境：

```bash
conda run -n agent python -c "import rapidocr"
```

若该环境确实未安装依赖，重新运行前述 `pip install -e '.[dev]'`。不要先切换到系统 Python。

**端口被占用**

停止先前启动器，或通过进程环境设置不同的 `FIGURA_GATEWAY_PORT` 和 `VITE_DEV_PORT`。

**重启后 Run 失败，或工具显示需要对账**

先查看 Run 状态和安全错误摘要。结果未知的模型请求不会无条件重发；只有可重建的纯生成请求在旧执行 owner 已退出且仍有尝试额度时才可能替换。需要对账的工具不会被盲目执行；在终态后可提交新消息。不要把 SSE 断开等同于任务已经停止。

**生成图中文字显示为方框**

渲染器使用本机字体，候选包括 PingFang SC、Arial Unicode MS 和 Noto Sans CJK SC。运行机器需要具有可用中文字体，尤其是在 Linux 环境中。

## 进一步阅读

- [系统总览](docs/figura-implementation-overview.md)：大组件关系、数据流与实现边界。
- [Agent](docs/figura/agent.md) · [Runtime](docs/figura/runtime.md) · [Memory](docs/figura/memory.md)：编排、恢复与对话投影。
- [Tools](docs/figura/tools.md) · [Sources](docs/figura/sources.md) · [Charts](docs/figura/charts.md)：观察工具、来源管理与图表合同。
- [Provider](docs/figura/provider.md) · [Web](docs/figura/web.md) · [Validation](docs/figura/validation.md)：模型、网页和共享校验边界；细节以当前代码与主规格为准。
- [Figura 主规格](openspec/figura/openspec/specs/) · [已完成变更归档](openspec/figura/openspec/changes/archive/)：主规格记录当前需求；归档保留对应 change 的设计、delta 与任务历史。`openspec sync` 同步主规格后，仍需完成归档步骤。
- [架构设计草案](docs/figura-architecture-design.md)：长期设计方向，其中尚未实现的能力以系统总览和当前代码为准。
