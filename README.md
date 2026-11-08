# 🐳 CodeMentor · 编程学习助手

> [!WARNING]
> **测试版本（v1.0.0-beta）· AI 辅助开发 · 功能尚未完善**
>
> - 本项目由 **AI 编程助手（大语言模型）主写代码 + 人工审校调试**，不是纯手工逐行编写；
> - 目前处于**测试阶段**：部分功能仍不完整（见下方「已知未完善」），接口、数据结构、界面都可能随时调整；
> - **仅供学习、课程演示与交流使用，请勿直接用于生产环境或对外提供服务**；
> - 使用时请自行评估风险，尤其是「屏幕演示」（会真的操控鼠标键盘）与「环境管家」（会真的安装软件、改 PATH）这两块。

> 一个会**先拆解任务、再调用工具、最后讲解并手把手演示**的编程学习 Agent。
> FastAPI + LangGraph + MySQL + Qdrant + Vue3，覆盖作业要求的全部六个阶段。

### 已知未完善（诚实清单）

| 方面 | 现状 |
| --- | --- |
| 屏幕演示 | 依赖视觉模型能力，复杂界面仍可能点偏/找不到控件；跨 DPI、多显示器场景未充分验证 |
| 环境管家 | 一键安装只在 Maven / PHP 上完整跑通，其余工具的 winget 包未逐个实测；部分包需要 UAC 提权 |
| 前端 | 只适配桌面端（≥1280px），手机/平板未做响应式；无前端单元测试 |
| 多用户 | 只有本地单用户（`users` 表预留 `user_id`，但没有登录/权限体系） |
| 向量检索 | 默认用离线哈希向量，语义能力有限；换成在线 embedding 需手动「重建索引」 |
| 工程化 | 无 CI/CD、无 Docker 镜像、覆盖率未统计；`docs/` 里部分数字会随迭代漂移 |
| 测试 | 后端 95 项单测 + 48 项端到端冒烟通过，但都是单机单账号场景 |

<p align="center">
  <img src="docs/screenshots/01-welcome.png" width="88%" alt="欢迎页" />
</p>

---

## 一、这个项目能做什么

| 能力 | 说明 |
| --- | --- |
| 🧠 **自主规划** | 收到问题后先由「规划器」输出 2~4 步 JSON 计划，再由「执行器」按计划调用工具，最后「讲解员」组织答案。回答里的计划、每一步状态都实时显示在右侧面板 |
| 🔧 **18 个工具** | 知识库检索、Python 代码沙箱、记忆写入/召回、屏幕演示提案、看一眼屏幕、**当前窗口**（前台进程 + 标题 + exe 路径）、**进程列表**（谁在跑 / 谁吃内存，可按名字或 PID 过滤）、本机文件（列目录 / 搜文件 / 读文本 / 打开 / 定位 / 列磁盘）、联网搜索、网页取正文、任务拆解与勾销 |
| 🛡 **工具异常自愈** | 工具内部任何异常都会转成 `{ok:false,error,hint}` 结构返回给模型，模型据此解释并给替代方案，界面不会崩 |
| 💬 **多会话隔离** | 每个会话独立的消息表、独立上下文、独立标题，可重命名 / 清空 / 删除 |
| 💾 **截图占用可见可清** | 侧边栏每条对话显示它的演示截图占了多少 MB，悬停图标即可只清这个对话的截图（文字记录保留）；删对话时截图自动跟着删；顶部还显示总占用并支持一键清掉「没挂到任何对话上」的历史演示 |
| 🧾 **双层记忆** | 短期：最近 N 条消息 + 滚动摘要；长期：跨会话事实/偏好写入 MySQL，并用 Qdrant 语义召回 |
| 📚 **RAG** | 文档切片 → 向量化 → Qdrant 入库 → 混合检索（向量 0.62 + 关键词 0.38），内置 10 篇编程知识包 |
| 🖼 **多模态** | 图片提问：**点「图片」选择 / Ctrl+V 粘贴截图 / 直接拖进输入框**，缩略图点一下就能放大（滚轮缩放、放大后可拖动、Esc 关闭）；屏幕演示自动把截图喂给视觉模型 |
| 🖥 **屏幕演示** | 截图（带 0~1000 坐标网格）→ 视觉模型决策 → 执行鼠标键盘。支持**组合键/快捷键**（Win+R、Alt+Tab、Ctrl+Shift+P…）、批量 sequence、拖动、滚轮、中文输入；逐步记录，可暂停续跑 |
| 🔑 **多模型热切换** | DeepSeek / 通义千问 / 智谱 / Kimi / 豆包 / 硅基流动 / OpenRouter / Groq / OpenAI / Ollama 本地 / 自定义端点（共 11 家），Key 加密落库、重启即用 |
| 🧰 **环境管家** | 「设置 → 环境」检测本机 24 个开发工具，一键 winget / 官方 zip 安装（后台任务 + 实时日志 + 默认写 PATH），并读注册表识别 `.py/.java/.js` 的默认打开方式自动补进编辑器快捷键库 |
| ✨ **界面** | 深色 / 浅色双主题（可跟随系统），三栏布局，流式打字、计划时间线、工具卡片、代码高亮与一键复制 |

### 界面速览

<table>
<tr>
<td width="50%"><img src="docs/screenshots/04-answer-demo.png" alt="智能体回答" /></td>
<td width="50%"><img src="docs/screenshots/06-trace-panel.png" alt="执行轨迹" /></td>
</tr>
<tr>
<td><img src="docs/screenshots/09-settings.png" alt="模型接入设置" /></td>
<td><img src="docs/screenshots/08-knowledge-panel.png" alt="知识库面板" /></td>
</tr>
<tr>
<td><img src="docs/screenshots/07-memory-panel.png" alt="长期记忆" /></td>
<td><img src="docs/screenshots/11-screen-console.png" alt="屏幕演示控制台" /></td>
</tr>
<tr>
<td><img src="docs/screenshots/light-01-welcome.png" alt="浅色主题" /></td>
<td><img src="docs/screenshots/light-03-answer.png" alt="浅色主题回答" /></td>
</tr>
</table>

---

## 二、技术栈

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 编排 | **LangGraph** `StateGraph` | `plan → act ⇄ tools → answer` 的真实环形状态图 |
| 模型适配 | **LangChain** `ChatOpenAI` | 统一走 OpenAI 兼容协议，一套代码接所有厂商 |
| 后端 | **FastAPI** + Uvicorn | REST + SSE 流式，全异步 |
| 数据库 | **MySQL 8**（SQLAlchemy 2.0 async + aiomysql） | 连不上时自动降级 SQLite，保证零配置可跑 |
| 向量库 | **Qdrant**（官方 embedded local 模式） | `QDRANT_MODE=remote` 可无缝切到服务端 |
| 前端 | **Vue 3** + Vite + Pinia + TypeScript | 组合式 API，无重型 UI 框架，全部手写设计系统 |
| 屏幕控制 | mss + Pillow + pyautogui | 截图识别间隔可调，鼠标移到左上角可紧急中止 |

---

## 三、快速开始

### 3.1 环境要求

- Windows 10/11 / macOS / Linux
- Python **3.10+**（开发验证于 3.12.6）
- Node.js **18+** + pnpm（或 npm）
- MySQL **8.0**（可选：没有会自动用 SQLite）
- 不需要 Docker、不需要单独部署 Qdrant

### 3.2 一键启动（Windows，最简单）

双击根目录的 **`start.bat`**，它会自己做完下面这些事：

1. 没有 `.venv` 就建一个（有 `uv` 用 `uv`，没有就 `python -m venv`）
2. 依赖没装、或 `requirements.txt` 改过就装一遍（默认源失败自动换清华镜像；uv 建的 venv 没有 pip 也能装）
3. 端口被占用自动往后找一个，**已经跑着本程序就直接开浏览器，不会起第二个**
4. 等 `/api/health` 通了自动打开浏览器

```
√ Python 环境就绪
√ 依赖已就绪（requirements.txt 没变）
√ 服务已就绪：http://127.0.0.1:8000
```

关掉窗口即停止服务。参数：`start.bat -Port 8100` / `-NoBrowser` / `-Reinstall` / `-Mirror`（网络慢就直接走清华镜像）。

> 等价命令：`powershell -ExecutionPolicy Bypass -File scripts\start.ps1`
> （`start.bat` 只是替你把执行策略和双击这两件事处理掉）

### 3.3 手动分步启动（要改代码时用）

```powershell
# 1) 后端
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 2) 前端开发服务器（热更新，另开一个终端）
cd frontend
pnpm install
pnpm dev            # http://127.0.0.1:5173

# 3) 或者一条命令起后端 + 前端开发服务器
.\scripts\start-all.ps1
```

> 只想看效果：先 `cd frontend && pnpm build`，之后直接访问 <http://127.0.0.1:8000>（后端会把 `frontend/dist` 一起托管），
> 包里自带构建好的 dist，所以 `start.bat` 不用装 Node。

### 3.4 关于模型

**第一次启动需要配一个 Key**（不再提供「内置演示模型」——它只会返回写死的假回答，测不出真实问题）。
没配时界面直接提示去配置，不会假装能跑。

接入真实模型：点左下角模型芯片 → 「模型接入」→ 填 Key → 点 **「保存并启用」**
（一步完成「加密落库 + 切换过去」；只想验证 Key 就先点「测试连接」，通过后会顺手保存）。

| 供应商 | Base URL | 常用模型 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` / `deepseek-reasoner` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` / `qwen-max` / `qwen-vl-max`(视觉) |
| OpenAI 兼容 | `https://api.openai.com/v1` | `gpt-4o-mini` / `gpt-4o`(视觉) |
| Ollama 本地 | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` / `qwen2.5vl:7b`(视觉) |
| 自定义 | 任意 `/chat/completions` 端点 | LM Studio、vLLM、one-api… |

**模型列表是运行时拉取的**：保存好 Key 后，后端会请求该供应商的 `GET /models`（Ollama 用 `/api/tags`），
把账户里真实可用的模型合并进下拉框 —— 厂商上新模型（例如 DeepSeek 的 V4 系列）不需要改代码就能出现。
拉不到时会退回内置推荐，模型名也支持**手动填写任意值**（在「模型接入」的对话模型输入框里直接敲）。

Key 用 Fernet 对称加密后存进 MySQL，密钥文件在 `data/.fernet.key`，
接口只回传 `sk-abc****4567` 形式的掩码，重启后自动解密即用。

### 3.5 配置项

复制 `.env.example` 为 `.env` 按需修改，常用：

```ini
DATABASE_URL=mysql+aiomysql://root:root@127.0.0.1:3306/code_mentor?charset=utf8mb4
QDRANT_MODE=local            # local | remote
EMBEDDING_PROVIDER=auto      # auto=离线哈希向量；api=在线 Embedding；local=sentence-transformers
EMBEDDING_DIM=512
AGENT_MAX_ITERATIONS=6
AGENT_FS_TOOL=true           # 只读文件工具开关
FS_ROOTS=                    # 额外允许的根目录，分号分隔
SCREEN_INTERVAL_MS=3000
SCREEN_DRY_RUN=false
```

---

## 四、目录结构

```
homework2/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口、生命周期、静态托管
│   │   ├── core/                   # 配置 / 日志 / 加密 / 异常 / 事件总线 / 全局状态
│   │   ├── db/                     # 异步引擎、ORM 模型（11 张表）
│   │   ├── llm/                    # 供应商注册表、模型解析、连通性测试
│   │   ├── agent/
│   │   │   ├── graph.py            # ★ LangGraph 状态图（plan/act/tools/answer）
│   │   │   ├── runtime.py          # 一次运行的全部依赖
│   │   │   ├── prompts.py          # 三段式提示词
│   │   │   ├── demo.py             # ★ 阶段六：演示可用性判定
│   │   │   └── tools/builtin.py    # ★ 18 个工具（含异常自愈契约）
│   │   ├── rag/                    # 切片器、Embedding、Qdrant 封装、内置知识包
│   │   ├── memory/                 # 短期上下文 + 滚动摘要 + 长期记忆
│   │   ├── screen_agent/           # 截屏、动作执行器、演示控制器
│   │   ├── services/              # ★ chat_service 编排 + env_install 一键安装 + default_apps 关联识别
│   │   ├── api/routes/             # 10 组 REST 接口
│   │   └── schemas/                # Pydantic 入参出参
│   ├── tests/test_units.py         # 56 个单元测试
│   ├── tests/test_env_manager.py   # 24 个环境管家单元测试
│   ├── tests/test_screenshot_usage.py  # 15 个截图统计/清理单元测试
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.vue                 # 三栏布局
│   │   ├── components/             # 侧边栏 / 消息 / 输入框 / 面板 / 弹窗（含设置-环境）
│   │   ├── stores/                 # Pinia：app / screen / ui
│   │   ├── api/client.ts           # REST + SSE 流解析
│   │   ├── styles/global.css       # 设计系统
│   │   └── utils/                  # markdown 渲染、格式化
│   └── scripts/                    # 无头 Chrome 自动截图（screenshot / shoot-env / shoot-initial）
├── start.bat                       # ★ 双击即可启动（建环境 + 装依赖 + 起服务 + 开浏览器）
├── scripts/                        # start.ps1 一键启动、start-* 开发模式、冒烟测试、打包
├── release/                        # 打好的「初始版」zip
├── docs/                           # 架构设计、视频脚本、验收对照、截图
├── data/                           # 运行时数据（SQLite 回退、Qdrant、截图、上传）
├── docker-compose.yml              # 可选：MySQL + Qdrant 容器
└── .env.example
```

---

## 五、核心设计

### 5.1 自主规划：LangGraph 状态图

```
        ┌────────┐
START → │  plan  │  输出 JSON 计划（2~4 步）
        └───┬────┘
            ↓
        ┌────────┐  有 tool_calls
        │  act   │ ───────────────┐
        └───┬────┘                ↓
            │ 无工具调用       ┌────────┐  还有轮次 → 回 act
            ↓                  │ tools  │ ─────────────┐
        ┌─────────┐ ←──────────└───┬────┘              │
        │ answer  │ ←──────────────┘ 轮次用尽/超预算    │
        └────┬────┘                                    │
             ↓                                          │
            END  ←───────────────────────────────────────┘（轮次未用尽时）
```

代码：`backend/app/agent/graph.py`。每个节点都会通过 `emit()` 把事件推给 SSE，
前端因此能实时渲染「任务规划 → 执行第 N 轮 → 工具调用 → 生成讲解」的完整链路。

### 5.1.1 时延优化：一轮对话从 4 分钟压到 30 秒

慢的本质不是代码，而是**串行的模型往返次数**。一轮回答原本至少要 `plan + act + act + answer`
四次全量 prefill，每次 5~30s，再乘上工具轮次就是几分钟。做了六件事：

| 优化 | 做法 | 效果 |
| --- | --- | --- |
| **工具并行** | `tools_node` 用 `asyncio.gather` 并发执行，不再 for-await 串行 | 3 个工具从「求和」变「取最大」，实测 3 个工具共 0.36s |
| **少走一轮** | 工具执行完若轮次用尽，**直接进 answer**，省掉"再问模型要不要调工具"那次调用 | 固定调用数 4 → 3 |
| **通信复用** | `build_chat_model` 加进程内客户端缓存，同参数复用连接池 | 省掉每次调用的 TCP/TLS 握手 |
| **规划器瘦身** | JSON 模式 + `max_tokens=500` + `temperature=0.1` | 规划更快、解析更稳（不支持 JSON 模式自动回退） |
| **证据瘦身** | 给 answer 的工具证据从 1500 字/条压到 420 字/条 | 首字前 prefill 明显变短 |
| **快车道** | 寒暄跳过 plan+act；短概念题跳过 plan 且**直接检索**再作答 | 问候 1 次调用、概念题 2 次调用 |
| **预算与轮次** | `agent_tool_rounds`（默认 1）、`agent_budget_s`（默认 90s）双保险 | 杜绝"一轮跑 4 分钟" |

实测（同一问题、同一个模型 `qwen3.8-flash`）：

| 场景 | 优化前 | 优化后 |
| --- | --- | --- |
| 「你好」 | ~3 次往返 | **6.7s**（首字 2.7s） |
| 「什么是闭包」 | ~4 次往返 | **12.3s**（首字 6.5s） |
| 装饰器 + 跑代码 | 211 ~ 274s | **27.1s**（首字 17s） |

另外两个开关在「设置 → 运行参数」：`关闭思维链`（通义 Qwen3 系列生效，思考型模型单跳 20s+
可降到几秒）和 `单轮时间预算`。

### 5.2 工具异常自愈

所有工具遵守同一条契约——**永不把异常抛给编排层**：

```python
return json.dumps({"ok": False, "error": "...", "hint": "..."})
```

`tools_node` 还有第二层 `try/except` 兜底（工具自身炸了也不会中断整轮）。
模型收到 `ok:false` 后会在回答里自然说明「我这边查库/跑代码没成功」并给替代方案，
前端同时把该工具标红并展示错误原因。验证用例：提交 `os.system('...')` 会被沙箱拒绝，
整轮对话仍然正常产出答案。

### 5.2.1 两个智能体怎么互通

对话智能体和屏幕智能体原本各跑各的：你在对话里说「我屏幕上这个报错」，它其实什么都没看见，
生成的演示指令自然容易跑偏。现在有一条双向通道（`screen_agent/context.py`）：

| 方向 | 机制 |
| --- | --- |
| 对话 → 屏幕 | 新工具 **`look_at_screen`**：截一张当前屏幕交给视觉模型，回答「报错是什么 / 当前开着哪个文件」 |
| 屏幕 → 对话 | 观察结果写进共享上下文，下一轮提示词自动带上「前台应用 + 看到的画面 + 细节」 |
| 屏幕演示 | 演示开始时也读同一份上下文，模型知道「你刚才就在 VS Code 里」，指令能落到具体窗口 |

保护措施：

- **限流**：同一用户 8 秒内只允许看一次屏幕，防止模型刷屏截屏；
- **TTL**：观察结果 5 分钟过期，避免用旧画面误导（过期后提示词里不出现）；
- **可关**：设置 → 运行参数 →「允许对话智能体看一眼屏幕」，关掉后该工具直接不绑定；
- **只做描述**：视觉模型的系统提示是「只客观描述、不给操作建议」，避免两套决策打架。

实测（用一张合成的测试截图验证，不涉及真实桌面）：

```json
{"ok": true, "app": "msedge",
 "summary": "当前处于 CodeMentor Screen Test 的屏幕测试界面，正在显示一段程序运行时的错误信息。",
 "details": "报错的文件位置为 File: demo.py Line 12。 / 具体的红色报错文字内容为 NameError: name x is not defined。",
 "screenshot": "/static/screenshots/shared/1793789765696.png"}
```

### 5.3 RAG 细节

- **切片**：按标题/空行切 700 字块，**代码围栏整体保留**，长度按还原后的真实文本计算
- **向量**：默认离线哈希向量（中文 1~2 字滑窗 + 英文标识符哈希到 512 维，L2 归一化），
  不依赖外网；配置 `EMBEDDING_PROVIDER=api` 可切到 `text-embedding-v3` 等在线模型
- **检索**：向量召回 Top-K×4 → 用 `0.62×余弦 + 0.38×关键词重合` 重排 → 取 Top-K
- **存储**：Qdrant 两个集合 `code_knowledge` / `long_term_memory`，payload 里带
  `doc_id / title / source / tags / chunk_index / text`

### 5.4 双层记忆

| 层 | 位置 | 策略 |
| --- | --- | --- |
| 短期 | `memory/service.py::build_context_messages` | 取最近 12 条消息 + 会话摘要，作为本轮上下文 |
| 摘要 | `maybe_summarize` | 消息数超过阈值时用 LLM 压缩成 200 字摘要，控制上下文长度 |
| 长期 | `extract_candidate_memories` | 用模式规则从用户话里抽取「偏好/画像/目标/事实」 |
| 召回 | `recall_memories` | 先用 Qdrant 语义召回，命中后按 id 回查 MySQL 过滤，最后更新访问计数 |

### 5.5 屏幕演示（阶段五 / 六）

```
截图(mss) + 0~1000 坐标网格 → JPEG data URL
      ↓
视觉模型（只回 JSON：thought + action + done）
      ↓
动作规范化（键名别名/组合键拆分/序列校验）→ 执行器
      ↓
ScreenStep 落库（先写 pending 再执行）→ SSE 广播 → 前端时间线
```

**支持的动作**（`screen_agent/actions.py`）：

| 类别 | 动作 | 说明 |
| --- | --- | --- |
| 鼠标 | `click` / `double_click` / `right_click` / `move` / `drag` / `scroll` | 坐标 0~1000 归一化，按真实分辨率还原 |
| 键盘 | `key` / `hotkey` | 单键 enter/esc/tab/f1-f12/方向键…；组合键写 `["ctrl","shift","p"]` 或 `"win+r"`、`"alt-tab"` 都能解析 |
| 批量 | `sequence` | 一次执行 2~6 个可预期动作，如「Win+R → 输入 notepad → 回车」 |
| 文本 | `type` | 中文自动走 Win32 剪贴板 + Ctrl+V |
| 其它 | `wait` / `done` | 等待界面加载 / 结束演示 |

**让它「更聪明」的四个设计**：

1. **快捷键优先**：系统提示词里内置了一张「Win+R / Win+E / Win+D / Alt+Tab / Win+Tab /
   Ctrl+Shift+Esc / Ctrl+Shift+P / Ctrl+S…」工具箱，并明确要求「能用快捷键就别猜坐标」。
   猜坐标是视觉模型最容易失败的动作，用 Win+R 打开程序比在开始菜单里找图标稳得多。
2. **坐标网格**：送给模型的截图会叠加 10×10 的青色网格和 0~1000 刻度，模型可以直接读数；
   存盘给界面看的是不带网格的原图。
3. **上下文与防呆**：提示词带上最近 3 步的「动作 → 结果」和「当前应该推进到哪一步」；
   同一动作连续 3 次没让界面变化就自动暂停，而不是一直原地点击。
4. **容错**：模型给出非法键名/缺坐标时，`normalize_action` 抛出可读错误 →
   本轮降级为 `wait` 并在 thought 里写明原因，会话不会崩；模型把 action 写在顶层也能解析。

**「识别间隔」到底是什么**：控制台滑杆（`SCREEN_INTERVAL_MS`，0.8~10s）是**每轮决策的目标周期**，
不是图片上传排队间隔。一轮是「截图 → 送模型 → 执行动作 → 等待」，等待时间是
`max(0.25s, 间隔 − 本轮已耗时)`，所以模型慢时不会再多等一整个间隔。
每一步都会重新截一张完整截图（缩放到 1024 宽、JPEG q65）送给视觉模型，没有图片复用或缓存。

**让屏幕演示更快**（模型慢时尤其明显）：

| 手段 | 说明 |
| --- | --- |
| 输出上限 | 决策输出 `SCREEN_MAX_TOKENS=320`（动作 JSON 本来就很短），生成时间大幅缩短 |
| 关思维链 | 通义 Qwen3 系列自动带 `enable_thinking=false`（不支持的模型自动回退普通调用） |
| 缩图 | 1280 → 1024 宽、质量 72 → 65，视觉 token 少约 36%，首字更快 |
| 自适应间隔 | 等待 = 间隔 − 本轮耗时，避免"模型 8s + 再等 2s"的叠加 |
| 换视觉模型 | 「设置 → 模型接入」里的 `vision_model` 与聊天模型独立，可单独指定更快的多模态模型 |

**输入法导致的乱码，三层防护**（`screen_agent/actions.py`）：

| 层 | 做法 | 解决什么 |
| --- | --- | --- |
| ① | 文本输入默认走 **剪贴板 + Ctrl+V**（`SCREEN_TYPE_MODE=clipboard`），不再用 `pyautogui.write` 逐字敲 | 输入法完全不参与：不会有全角字符、丢字、候选框吞回车 |
| ② | 落键前把代码里的 **全角标点纠正成半角**：`print（"hi"）；` → `print("hi");` | 模型自己吐全角、或上一次粘贴带进来的脏字符；中文散文不会被误改 |
| ③ | 演示期间尝试把前台程序 **切到英文输入法**（Win32 IMM，结束自动还原，可在控制台关掉），提示词里还要求「输入后自检，不一致就 Ctrl+A 整段重输」 | 只对必须回退到模拟按键的情况兜底 |

> 实测：`ImmGetContext` 对 Edge / VS Code 返回空（它们用 TSF 而不是 IMM），所以 ① + ② 才是主防线，
> ③ 是加分项；界面会如实提示「当前程序不支持自动切输入法」。

**会踩坑、会记路：经验库**（`screen_agent/memory.py` + `screen_lessons` 表）

以前它会在同一个失效操作上反复试几次；现在每一步都用「下一帧画面变没变」来判卷：

| 判定 | 处理 |
| --- | --- |
| 画面变了 | 记为**有效做法**（按前台应用分域），下次同款应用优先复用 |
| 画面没变 | 记为**无效做法**，立刻进本次会话的禁用表，再出现就直接跳过 |
| 同一动作重复 | 不等三次：第二次就判失效并跳过；指纹按 100×100 像素归一，抖动几十像素算同一个动作 |
| 连续 3 次无效 | 自动暂停，把控制权交回你 |

经验会回灌到提示词：「已验证有效，优先复用」「已验证无效，不要再试」；系统提示词里也写明了
**预设步骤只是参考路线，走不通就跳过或换路线**，不再死板按步骤走。

**从对话里学**：你说过「用 Ctrl+Shift+P 打开命令面板」，创建演示时会自动提取成经验
（只认带指令动词的，避免把「Ctrl+S 是保存」这种顺口一提也记进去）。

控制台底部有「🧠 经验库」面板，能看到学到了什么、也能一键清空；接口
`GET /api/screen/lessons`、`DELETE /api/screen/lessons`。

阶段六的两个硬约束都落在代码里：

1. **只有「有效编程内容」才允许弹出启动入口**
   `agent/demo.py::analyze` 综合打分：有代码块 +3、有编号步骤 +2、有动手动词 +2、
   工具成功 +1、计划要求演示 +1，`score ≥ 4` 且（有代码 或 ≥2 个步骤）才 `available=True`。
   纯理论回答（如「装饰器是闭包」）会明确显示「本轮不提供屏幕演示」。
2. **暂停必须记住当前步骤**
   每步先把 `current_step` 与 `ScreenStep(pending)` 落库，再执行动作；
   暂停只是清掉 `asyncio.Event`，恢复时从 `current_step` 继续；
   服务重启时 `recover_stale()` 把 `running` 的会话标记为 `paused`，日志文案提示可从第 N 步续跑。

### 5.7 外观：三档主题 + 自定义背景

设置弹窗现在是四个页签：**模型接入 / 外观 / 运行参数 / 关于**，视觉相关的东西全部收进「外观」。

**背景画面**：支持图片和循环视频（自动静音、`loop`、`playsinline`）。

| 能力 | 说明 |
| --- | --- |
| 素材库 | 上传过的图片/视频以缩略图排在面板里，点一下即应用；悬停可删除 |
| 实时预览 | 左侧预览与右侧控件**等高排布（约 1:1 的方正比例）**，里面按真实布局画出**侧栏 / 主区 / 右栏线框**——圆点和色块占位，不画具体图标文字；点「放大」可铺满整宽 （16:9）。模糊、遮罩、画面不透明度、左右栏不透明度都所见即所得 |
| 外部 URL | 直接填 `https://.../loop.mp4`，按后缀自动判断图片还是视频 |
| 五个滑杆 | 模糊 0~40px、遮罩 0~80%、画面不透明度 10~100%、**左栏不透明度**、**右栏不透明度**（两栏独立） |

文件落盘在 `data/backgrounds/`（≤60MB，后缀白名单 + UUID 命名），本地只存 URL 和这五个数值，
所以换浏览器也不会丢配置；点「无」立刻恢复原来的渐变底。

**半透明怎么生效**：启用后根节点打上 `html[data-bg="on"]`，全局表面 token 换成半透明版本
（`--surface / --panel-bg / --composer-bg / --bubble-bg / --dialog-bg`），
气泡、输入框、弹窗走毛玻璃，侧栏与右侧面板则**直接透出清晰画面**，透明度由各自的滑杆控制。

| 关注点 | 做法 |
| --- | --- |
| 只改 token 不改组件 | 面板本来就用同一套 CSS 变量，重定义变量即可全局生效 |
| 两栏各自可调 | `--panel-alpha-left` / `--panel-alpha-right` 两个变量，互不干扰 |
| 亮图也能看清 | 媒体层之上压一层可调遮罩（深色黑 / 浅色白），文字再加极淡投影 |
| 视频不抢焦点 | 背景层 `pointer-events: none` + `aria-hidden`，不进交互也不进读屏 |
| 配置只在本地 | 主题与背景参数存 localStorage，素材文件在后端，两边解耦 |

截图见 `docs/screenshots/25-bg-welcome.png`（首页）、`26-bg-settings.png`（外观页）、
`27-settings-runtime.png`（运行参数页）。
---

### 5.8 本机文件：只读，改动一律走键鼠

屏幕智能体靠"看"找不到文件，所以补了一组**文件系统工具**（`agent/tools/files.py`）：

| 工具 | 能力 |
| --- | --- |
| `list_dir` | 列目录（名字/类型/大小/时间）；**path 留空会直接返回所有允许的根目录**，避免模型猜 `C:\Users` |
| `find_files` | 按名字搜**文件和文件夹**，返回绝对路径；多盘并行 + 时间预算（默认 8s，可调 2~25s）；装了 Everything（`es.exe`）则毫秒级全盘 |
| `list_drives` | 枚举所有磁盘（盘符 / 类型 / 容量 / 是否可读），搜不到时先看它，再带 `root="I:\"` 精确搜 |
| `read_file` | 只读预览文本（≤200 行 / ≤2MB），用来确认「是不是这个文件」 |
| `open_path` | 用默认程序打开（**拒绝 exe/bat/ps1/lnk 等可执行与脚本**） |
| `reveal_in_explorer` | 打开资源管理器并选中文件，讲课时指给学习者看 |

**为什么只读**：写入、删除、重命名这类操作**一律不给**。要改文件只能走「屏幕演示」——
视觉模型驱动键盘鼠标在真实界面里操作，学习者全程看得见、随时能暂停。这条边界写在
代码（没有写接口）、提示词（明确禁止直接改）、UI（开关叫"只读"）三处。

安全边界：

| 措施 | 说明 |
| --- | --- |
| 根目录范围 | 默认放开**所有磁盘**（`fs_allow_all_drives`，只读），可在设置里关掉退回白名单；另外始终拒绝系统目录和别人的用户目录 |
| 系统目录拒绝 | `C:\Windows`、`Program Files`、`ProgramData`、回收站等直接拒 |
| 路径规范化 | `resolve()` 之后再比对白名单，`..\..\` 穿越绕不过去 |
| 可执行拦截 | `open_path` 遇到 exe/bat/ps1/lnk 等直接拒绝并提示改走屏幕演示 |
| 用量限制 | 单次最多 200 条、扫描上限 2 万项、深度 ≤6，不会把整盘扫爆 |

**多段式任务**：文件类工具（列目录/搜索/打开）几乎不耗时，所以轮次用尽时系统会额外放行一到两轮，让「先搜索 → 再打开」这种流程能走完，而不是搜到就断。

**和屏幕演示打通**：本轮用文件工具定位到的绝对路径会记进 `ctx.paths`，
`propose_screen_demo` 会把它们一起返回（`known_paths`）。屏幕侧拿到路径后直接
`Win+R → 输入路径 → 回车`，比在资源管理器里逐层点图标稳得多。

#### 控件树（UI Automation）：不靠看，直接问 Windows

截图 + 估坐标本质是在像素里猜。Windows 的 UIA 直接把「这个按钮叫什么、在哪个矩形」交出来，
点击就退化成「取矩形中心」。这是从参考项目 `dsh-pilot`（`_dsh-uia.ps1`）学来的思路，
这里用纯 Python 的 `uiautomation`（ctypes 直连，无需 .NET）。

| 动作 | 作用 |
| --- | --- |
| `{"type":"controls"}` | 读前台窗口的控件树（可带 `title` 指定窗口），结果下一轮注入提示词 |
| `{"type":"click_control","index":14}` | 点击 14 号控件的矩形中心（换算成归一化坐标后走原有安全链路） |
| `{"type":"invoke_control","index":14}` | InvokePattern 直接触发，等价点击但完全不受坐标影响 |
| `{"type":"set_control","index":7,"text":"..."}` | ValuePattern 直接赋值，**彻底绕开输入法** |

实测（资源管理器窗口，53ms）：

```
[ 5] Button '返回到 dsh-pilot (Alt + 向左键)' @ 93,312 45x45
[ 6] Button '前进 (Alt + 向右键)'            @ 138,312 45x45
[ 9] Button '上移到“homework2”(Alt + 向上键)' @ 208,317 36x36
[13] Pane   '文件夹布局窗格'                  @ 87,360 1925x898
```

**边界**：浏览器网页内部、游戏画面通常拿不到控件树（浏览器默认不开 renderer 无障碍），
那些场景仍走截图 + 网格 + zoom。

#### 另外两条来自参考项目的加固

1. **per-monitor DPI v2**：抓屏和点击都必须声明同一套 DPI 感知，否则 2560×1600 会被系统
   报成 1707×1067，算出来的点击必然偏。现在 `capture.py` / `actions.py` 在导入 mss / pyautogui
   之前统一声明（实测 `per-monitor`，两边都读到 2560×1600）。
2. **落点校验**：每次点击后读一次真实光标位置，偏差超过 3px 就在结果里写
   「⚠️光标实际落在 (x, y)，偏差 (+dx, +dy)，坐标可能被缩放假偏」——把「点不准」变成可观测的信号。

#### 定位精度：字够大，是网格太粗

实测这台机器是 **2560×1600 @ 150% 缩放**（`GetDeviceCaps(LOGPIXELSX) = 144`）。
换算下来字并不小：

| UI 字号(逻辑) | 物理像素 | 缩到 1568 后图内 |
| --- | --- | --- |
| 12px | 18px | 11.0px |
| 14px | 21px | 12.9px |
| 16px | 24px | 14.7px |

所以「认不出字」不是主因，**真正的短板是坐标精度**：旧的 10×10 网格每格 256 物理像素
（约 45mm），而一个工具栏图标只有 24~36px——模型要在比目标大 7 倍的格子里估位置，
偏一格就是几十像素，自然点空。

三处改动：

1. **网格加密到 20×20**：每格 128px，粗线每 100、细线每 50，瞄半格也有依据
2. **重试时自动放大 + 红色准星**：第二次失败不再盲点，而是把刚才那块区域放大，
   并在图中画出「上次点击位置」的准星——模型能直接看到偏了多少，据此修正坐标
3. **放大视图的网格数字仍是全屏 0~1000**，坐标不用换算

另外截图宽度保持 1568（不是 1024），JPEG 质量 85，避免文字边缘振铃。

#### 节奏控制：抓帧快、思考慢

| 参数 | 默认 | 作用 | 性质 |
| --- | --- | --- | --- |
| `screen_capture_ms` | **200ms**（可低至 100） | 抓帧节奏，用来判断界面有没有变 | 便宜，~50ms |
| `screen_interval_ms` | **5000ms** | 两次「问模型」之间的最小间隔 | 贵，2~8s |
| `screen_skip_unchanged` | 开 | 画面完全没变就不调模型（连续 8 次约 4s 强制问一次） | — |

两者独立：**抓帧可以很快，送模型要慢**。而且循环是串行的——一次决策没返回，根本不会抓下一帧，
所以不存在「还没想完又把新画面塞进去」。

实测（决策间隔 5000ms、模型耗时 0.3s）：

```
13 秒内模型调用 3 次，间隔 [5.26s, 5.01s]
```

#### 一帧内的思考循环

```
抓一张截图
  → 思考：要不要先取证？
      ├ probe: controls（读控件树）
      ├ probe: windows（列窗口）
      └ probe: value #7（读输入框内容）
  → 取证结果累积在 frame_context，重新思考（最多 3 轮）
  → 给出一个动作 → 执行 → 等界面稳定 → 抓下一帧（frame_context 清空）
```

实测一帧内思考 2 轮：模型调用 3 次、抓帧 2 次，帧内上下文条数 `[0, 1, 0]`（换帧清空）。

#### 中断与强制停止

**演示什么时候会停**——原则是「**不轻易暂停，只有模型出错才中断**」：

| 触发 | 状态 | 说明 |
| --- | --- | --- |
| 视觉模型调用失败（网络/限流/超时） | 中断（failed） | 这是唯一的强制中断条件，进度已落库 |
| 模型自己认为目标达成 | 完成 | 正常结束 |
| 达到最大步数 | 完成 | 兜底，默认 200 步 |

**操作没反应怎么办**——不再暂停，而是按阶梯重试：

```
操作后画面没变化
  → 等 5 秒，原地再执行一次
  → 还没变化，等 10 秒，再执行一次
  → 仍然没变化（累计约 15 秒），判定这个做法作废
     · 记进本次会话的禁用清单
     · 给模型一条强指令「必须换方案」（换快捷键 / 换入口 / 先 esc 回稳）
     · 继续跑，不暂停
```

界面上会依次看到：「暂时没让界面变化，等 5 秒后原地重试一次」→「已重试（第 1 次）」
→「等 10 秒后原地重试」→「等了 15 秒仍无变化，已弃用，接下来换一种做法」。

**全局强制停止**：`Ctrl+Alt+Shift+F12`（可在设置里改）。用 Win32 `RegisterHotKey` 注册，
不抢焦点、不改键鼠状态，任何窗口下都生效；按下后所有演示立即停止并保存进度（可续跑）。
另外 `pyautogui` 的 FAILSAFE 仍然有效——鼠标甩到屏幕左上角也能中止。

### 5.9 提示知识（guide）与本机环境画像

知识库里其实有两种东西，用 `kind` 区分：

| 类型 | kind | 去向 | 用途 |
| --- | --- | --- | --- |
| 知识文档 | `doc` | 切块后进 Qdrant，被 `knowledge_search` 语义检索 | 回答「是什么 / 怎么做」 |
| **提示知识** | `guide` | **不进向量库**，每轮原样注入系统提示词 | 约束模型「怎么做事的」 |

提示知识再按 `target` 分发给不同智能体：

- `chat` → 注入规划器与执行器的系统提示词；
- `screen` → 拼在屏幕智能体的 SYSTEM_PROMPT 后面；
- `both` → 两边都给。

在「知识库」面板点「+ 新增」，选「🧭 提示知识」，再选作用对象就能写。例子：

```
屏幕操作：优先快捷键 + 先确认窗口
- 打开程序优先 Win+R 输入完整路径，不要在开始菜单里找图标
- 每次点击前先确认截图里的窗口标题是否是目标程序
- 输入代码后立即 Ctrl+S 保存，再运行
```

**本机环境画像（自动生成）**：每次启动会采集当前机器信息，写进一条 `target=chat`
的提示知识（`source=system-profile`），内容包括系统版本、Shell、Python 版本、
虚拟环境写法、包管理器、数据库/向量库配置，以及一段硬约束：

> 只给 Windows 的做法；不要给 `apt` / `brew` / `sudo` / `export` / `/usr/local`；
> 路径用反斜杠；环境变量用 `$env:NAME`；如果学习者确实问 Linux，要先点明系统差异。

这样模型不会再拿 Linux/macOS 的命令来回答 Windows 的问题。实测提问「怎么用命令行安装依赖并设置环境变量」，
回答里 `pip install` + `$env:EXAMPLE_KEY` + PowerShell，`apt/brew/sudo/export` 一个都没出现。

#### 旧式 XML 工具调用兼容

部分模型（Qwen 系在个别 OpenAI 兼容端点上）会退化成下面这种**纯文本**调用格式，而不是
标准 `tool_calls` 字段：

```
<tool_call>
<function=list_dir>
<parameter=path>
E:\项目\demo
</parameter>
</function>
</tool_call>
```

不处理的话有两个后果：这段标签会被当成答案流式输出（界面上一堆乱码），本该执行的工具也不执行。
现在两层兜底（`agent/xml_calls.py`）：

| 机制 | 作用 |
| --- | --- |
| `parse_legacy_tool_calls()` | 在 `act` 节点检测到这种文本时，解析成结构化调用照常执行，并提示"已自动转换" |
| `LegacyTagFilter` | 流式过滤，答案里永远不会出现 `<tool_call>` / `<parameter>` 标签（支持跨 chunk 的半个标签） |

顺带两处加固：

- 工具参数改成**内部钳制**而不是 schema 硬校验：`depth=6`、`lines=500`、字符串 `"3"` 都不会再报
  ValidationError，超范围自动截断（写死 `le=3` 时模型给 6 会直接失败）
- 空知识库检索不再算失败：返回 `ok + count=0 + 提示`，界面不飘红，模型也不会反复重试

#### 轮次与递归上限

「先把项目读一遍再回答」这类任务要连读十几个文件。文件工具单次只要 ~10ms，所以：

- 便宜工具（列目录/搜索/读文件/打开）的轮次上限 3 → **6**
- LangGraph `recursion_limit` 从 `max(8, iters*3+6)` 改成 `max(40, iters*3+30)`：
  原来的公式在快车道（`max_iterations=1`）下正好算成 9，读文件到一半就 `GraphRecursionError`，
  用户看到的是"答了一句就没了"
- 触发递归上限也不再抛错，而是用已收集的证据给出小结，不会让整轮对话失败

### 5.11 联网搜索 / 原子步骤 / 中途提问 / 模型共用

四个针对实际使用痛点的补强：

**① 联网搜索（`web_search` + `web_fetch`）**——不依赖任何 API Key：

| 工具 | 说明 |
| --- | --- |
| `web_search(query, count)` | 抓 cn.bing.com 结果页并解析，返回标题/链接/摘要；Bing 不可用时自动降级到搜狗 |
| `web_fetch(url, max_chars)` | 抓网页正文、去 HTML 标签、截断 6000 字 |

安全：只允许 http/https，**拒绝内网与本机地址**（`127.x`、`10.x`、`192.168.x`、`localhost`、`ftp://` 等），
DNS 解析后还会再核一次，防止被诱导去扫本机端口。

**② 演示步骤改成原子步骤**——以前「打开记事本，写点代码然后保存」是一整条，屏幕侧的模型只能猜。
现在两道处理：

- 提示词要求「对象 + 动作 + 预期结果」，一步一个动作；
- 生成时再按 `，、；→ 然后 接着` 自动切分（`_split_step`），去掉序号、合并极短碎片，最多 8 步。

**③ 演示中途可以向学习者提问（ask）**——模型卡住时不再瞎猜：

```json
{"type":"ask","question":"你的项目在哪个目录？","options":["E:\a","E:\b"]}
```

会话转为 `waiting`，界面弹出输入框与选项按钮；提交后答案写进上下文并自动续跑
（`POST /api/screen/sessions/{id}/answer`）。提示词里也写清楚了「什么问题该问人、什么问题该自己判断」。

**④ 屏幕演示的模型可选/可共用**：

| 设置 | 效果 |
| --- | --- |
| `screen_share_chat_model=true` | 直接用对话侧那个模型（要求支持图片），两个智能体同一个脑子 |
| `screen_model_override="qwen:qwen3-vl-plus"` | 显式指定 provider:model |
| 都留空 | 自动挑该 provider 的多模态模型（原行为） |

### 5.12 任务拆解：一次只做一件，做完不丢

复杂需求（「装好环境、建项目、写接口、跑起来」）如果一口气做完，会糊成一片，屏幕演示也没法聚焦。
现在走「拆解 → 单件执行 → 持久化」三步。

**① 谁来拆**——两道保证：

| 层 | 做法 |
| --- | --- |
| 系统兜底（不依赖模型听话） | 在 `runtime.create` 里用 `detect_multi_action()` 扫描提问：按 `、，；然后 接着 最后` 切句，含两个以上动作动词就自动拆成任务清单落库，并在提示词开头强加「**本轮只做第 1 件**」 |
| 模型主动 | 提供 `plan_tasks(tasks[])` 工具，模型可自行细化（实测它会把我拆的 4 条改写成更准的 5 条） |

**② 一件一件做**：提示词规定「单点操作直接做；多个操作先拆清单，本轮只做第 1 件，结尾告诉学习者还剩几件」。

**③ 不丢**：任务存在 `agent_tasks` 表（conversation_id / idx / title / status），每轮对话都会重新读出来
注入提示词，所以：

- 关掉页面/重启后端再回来，清单还在；
- 每轮开头模型都知道「现在做第几件、还剩几件」；
- 界面输入框上方有「📋 任务清单 1/5」的折叠条，点一条就能标记完成。

接口：`GET /api/conversations/{id}/tasks`、`PATCH /api/conversations/{id}/tasks/{idx}`。

实测（同一句多任务需求）：

| 指标 | 加拆解前 | 加拆解后 |
| --- | --- | --- |
| 工具调用 | 15 次 | 5 次 |
| 耗时 | 187.8s | 76.5s |
| 输出 | 一口气讲完四件事 | 只讲第 1 件（环境检查），末尾提示还剩 4 件 |

### 5.13 模型接入：11 家供应商

| 供应商 | 端点 | 代表模型 | 视觉 |
| --- | --- | --- | --- |
| DeepSeek | `api.deepseek.com/v1` | deepseek-chat / deepseek-coder | — |
| 通义千问 DashScope | `dashscope.aliyuncs.com/compatible-mode/v1` | qwen3-max / qwen-plus / qwen3-coder-plus | **qwen3-vl-plus** 等 |
| 智谱 GLM | `open.bigmodel.cn/api/paas/v4` | glm-4.6 / glm-4-flash（免费额度） | glm-4.5v |
| 月之暗面 Kimi | `api.moonshot.cn/v1` | kimi-k2-0905 / moonshot-v1-128k | moonshot-v1-vision |
| 火山方舟 豆包 | `ark.cn-beijing.volces.com/api/v3` | doubao-seed-1-6 | doubao-seed-vision |
| 硅基流动 | `api.siliconflow.cn/v1` | DeepSeek-V3 / Qwen3-32B（托管） | Qwen2.5-VL-72B |
| OpenRouter | `openrouter.ai/api/v1` | GPT-4o mini / Claude Sonnet 4 / Gemini 2.5 Pro | ✅ |
| Groq | `api.groq.com/openai/v1` | llama-3.3-70b / qwen3-32b | Llama 4 Scout |
| OpenAI | `api.openai.com/v1` | gpt-4o / gpt-4o-mini | ✅ |
| Ollama（本地） | `127.0.0.1:11434/v1` | qwen2.5:7b / deepseek-r1:7b | qwen2.5vl:7b |
| 自定义端点 | 任意 OpenAI 兼容 | LM Studio / vLLM / one-api | — |

全部走 OpenAI 兼容协议，换供应商只改 base_url + Key。

**内置演示模型（mock）已移除**：它只会返回写死的假回答，测不出真实问题。现在默认供应商是
`deepseek`，未配 Key 时界面直接提示去配置，不再假装能跑。

### 5.14 环境管家：先量体温，再一键装，最后告诉智能体你在用什么编辑器

学编程的第一道坎往往不是语法，是环境：Python 装了没勾 PATH、JDK 版本对不上、Node 和工具链打架。
「设置 → 环境」把这件麻烦事拆成三步：**检测 → 一键安装 → 默认打开方式**。

#### ① 检测：24 个工具，约 1 秒扫完

`GET /api/env/probe` 用 `shutil.which` 找到可执行文件，再跑一次版本命令确认能启动。
24 个工具串行 spawn 要 2 秒以上，改成 8 线程并发后实测 1.0 秒（面板一打开就能看到结果）。

| 分类 | 工具 |
| --- | --- |
| 语言 | Python、Node.js、JDK、Go、Rust、.NET SDK、PHP、Ruby |
| 构建 | Maven、Gradle |
| 数据库 | MySQL、PostgreSQL、Redis、SQLite |
| 容器 | Docker、Docker Compose |
| 工具 | Git、npm、pnpm、Yarn、pip、Conda、CMake、GCC |

每张卡片给出：装没装、版本、路径（悬停看完整路径）、推荐版本、能不能一键装。

#### ② 一键安装：两种来源，一个后台任务

| 来源 | 适用 | 做法 |
| --- | --- | --- |
| **winget** | 有官方包的（Python / Node / JDK / Go / Redis / CMake / pnpm …） | `winget install --id X -e --silent --accept-package-agreements --accept-source-agreements`；支持自定义目录的包再加 `--location <安装根目录>/<工具>` |
| **zip** | winget 没有官方包的（Maven / Gradle） | 下官方压缩包（Apache / Gradle 优先，带清华、阿里、腾讯镜像兜底）→ 解压（自动剥掉顶层目录）→ 写 PATH |

点「一键安装」会弹一个**独立的二次确认弹窗**：显示将要执行的命令、安装位置，以及一个默认勾选的
「装完自动加入 PATH（推荐，新终端直接能用）」。确认后转成后台任务，面板变成**阶段性进度条**：
准备 → 下载/安装 → 解压 → PATH → 验证，每段是一个阶段，下载阶段还会按真实百分比推进；
下面只有**一行小字**显示当前进度，完整输出收在「详细日志」里（见 `docs/screenshots/47-env-progress.png`）。

**手动安装也是弹窗**（不再把卡片撑开）：最上方是官网入口（`go.dev/dl`、`gradle.org/releases` 这类），
下面是可**一键复制**、也可**一键运行**的命令，再往下是步骤与提示。点「一键运行」走的是和「一键安装」
同一条后台通道，所以照样有阶段进度、PATH 写入和版本验证；区别是日志第一行会写下
「手动命令：<你看到的那条命令>」，方便对照它到底跑了什么。

> 安全边界：`via=manual` 只是日志标记，**真正执行的命令永远来自服务端工具表**，
> 客户端只能传 `tool_id` —— 否则这个接口就等于一个本地 shell。

```
下载 https://dlcdn.apache.org/…/apache-maven-3.9.16-bin.zip
下载进度 33%（3.0 MB / 9.0 MB）
解压完成
找到可执行文件：D:\DevEnv\maven\bin
已加入用户 PATH：D:\DevEnv\maven\bin
验证通过：Apache Maven 3.9.16
```

几个实现上的关键点（对应 `services/env_install.py`）：

- **HTTP 不等安装**：`POST /api/env/install` 只校验入参、登记任务、起线程，立刻返回 `job_id`；
  前端用 `GET /install/{id}?since=N` 按游标拉增量日志，轻到可以每秒轮询。
- **进度用阶段表达**：后端在任务里维护 `stage`（prepare → download/install → extract → path →
  verify → done），前端按阶段权重画分段进度条；下载阶段再叠加日志里的百分比做细分，
  其余阶段靠当前段的呼吸动画表示「还在跑」，面板上只留一行小字显示当前那行输出。
- **进度条也是日志**：winget 用 `\r` 刷新进度，所以按 `\r\n|\r|\n` 切分二进制流，再按
  utf-8 → gbk → latin-1 依次解码（中文 Windows 上很常见）；完整输出放在「详细日志」折叠里。
- **终态最后才置**：找 exe、写 PATH、`--version` 验证这些收尾动作跑完，才把 `status` 改成
  `succeeded`；否则前端一看到终态就停轮询，正好漏掉最重要的几行。
- **PATH 要小心**：写之前备份到 `data/env_path_backup.json`，写回时保留原类型
  （`REG_EXPAND_SZ` 写成 `REG_SZ` 会把 `%USERPROFILE%` 固化），最后广播 `WM_SETTINGCHANGE`；
  安装程序自己已经加过的目录不会重复追加。
- **装完立刻可用**：把注册表 PATH 同步回后端进程，验证才不会被「环境变量没刷新」骗到。
- **Java 顺手设 `JAVA_HOME`**（指向安装根目录而不是 `bin`），很多构建工具只认它。
- **并发只允许一个**：两个安装程序同时改 PATH 很容易互相覆盖，第二个请求直接 409 + `ok:false`。

失败路径也都是结构化响应：没 winget、工具没有可自动安装的来源、并发冲突、任务不存在，
一律 `{ok:false, code, message, hint}`，前端弹 toast 而不是转圈。

#### ③ 默认打开方式：读注册表，写进编辑器快捷键库

`.py` 双击进 PyCharm、`.js` 进 VS Code —— 这个信息就在注册表里：

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.py\UserChoice  →  ProgId=PyCharm2024.2
HKEY_CLASSES_ROOT\PyCharm2024.2\shell\open\command                              →  "D:\…\pycharm64.exe" "%1"
exe 的 VERSIONINFO\…\FileDescription                                            →  PyCharm Professional Edition
```

Python 实现只用 `winreg` + `ctypes`（读版本信息取友好名称）。识别结果自动补进
「设置 → 编辑器」的**识别关键词**：屏幕智能体拿到的 `app_scope` 正是前台进程名（`pycharm64`、
`idea64`、`code`），命中后就把对应编辑器的快捷键注入提示词，演示时不用猜某个功能按什么键。

两类文件被刻意排除：浏览器（`.html` → Edge）和文档编辑器（`.md` → Typora），
它们不会进编辑器库——写进去只会污染提示词。写入是幂等的：已经在库里的条目只补关键词，
不覆盖手改过的快捷键，所以「重新识别」随时可以点。

截图：`42-env-overview.png`（面板全貌，安装路径已折叠）、`43-env-paths-open.png`（展开后编辑路径）、
`44-env-cards.png`（工具卡片）、`45-env-manual.png`（手动安装弹窗：官网入口 + 一键复制/运行）、
`46-env-confirm.png`（二次确认弹窗 + PATH 勾选）、`47-env-progress.png`（阶段性进度条 + 一行进度）、
`48-env-install-done.png`（装完 100%）、`49-editors-synced.png`（写进编辑器库）。

## 六、接口一览

| 分组 | 接口 | 说明 |
| --- | --- | --- |
| 系统 | `GET /api/health` | 数据库 / 向量库 / 计数 / 工具列表 |
| 模型 | `GET /api/providers`、`PUT /api/providers/{id}`、`POST /api/providers/{id}/activate`、`POST /api/providers/{id}/test`、`DELETE /api/providers/{id}/key`、`GET /api/providers/ollama/models` | 目录、保存（加密）、切换、连通性测试 |
| 会话 | `GET/POST /api/conversations`、`GET/PATCH/DELETE /api/conversations/{id}`、`DELETE /api/conversations/{id}/messages`、`GET /api/conversations/{id}/runs` | 严格隔离 + 删除 + Agent 轨迹 |
| 对话 | `POST /api/chat`（**SSE**） | 事件：`start / node / plan / tool_start / tool_end / token / thought / notice / memory_* / demo / done / error` |
| 文件 | `POST /api/files/upload` | 多模态图片上传（≤8MB） |
| 背景 | `GET/POST /api/backgrounds`、`DELETE /api/backgrounds/{name}` | 自定义图片 / 视频背景（≤60MB） |
| 知识库 | `GET/POST /api/knowledge`、`DELETE /api/knowledge/{id}`、`POST /api/knowledge/search`、`GET /api/knowledge/stats`、`POST /api/knowledge/{reindex,seed}` | 入库、检索调试、重建索引 |
| 记忆 | `GET/POST /api/memory`、`DELETE /api/memory/{id}`、`POST /api/memory/recall` | 长期记忆管理 |
| 屏幕 | `POST/GET /api/screen/sessions`、`POST .../{id}/{start,pause,resume,stop}`、`PATCH .../{id}/interval`、`GET .../{id}/events`（**SSE**）、`GET/DELETE /api/screen/lessons` | 演示全生命周期 + 经验库 |
| 设置 | `GET/PUT /api/settings` | 运行参数 |
| 环境管家 | `GET /api/env/probe`、`POST /api/env/install`、`GET /api/env/install/{id}?since=N`、`POST /api/env/install/{id}/cancel`、`GET /api/env/installs` | 检测 / 一键安装（后台任务 + 增量日志） / 取消 |
| 默认打开方式 | `GET /api/env/default-apps`、`POST /api/env/default-apps/apply` | 读注册表文件关联；把识别到的编辑器写进快捷键库 |

环境相关接口的响应**一律带 `ok`**（成功、业务失败、参数校验失败都带），前端只看这一个开关。

完整交互文档：启动后访问 <http://127.0.0.1:8000/docs>。

---

## 七、测试

```powershell
# 单元测试（纯函数，无需启动服务）
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_units.py -q
# 56 passed
.\.venv\Scripts\python.exe -m pytest tests/ -q
# 77 passed（含环境管家：日志切分、命令拼装、PATH 去重、镜像兜底、注册表解析）

# 端到端冒烟（需后端已启动）
.\.venv\Scripts\python.exe ..\scripts\smoke_test.py
# 通过 48 项，失败 0 项
```

冒烟测试覆盖：健康检查、Key 加密脱敏、知识库重建与检索、Agent 全流程 SSE、
多轮同会话、新会话隔离、长期记忆写入与召回、危险代码被拒、多模态上传、
屏幕演示创建→启动→暂停→续跑→结束、会话删除，以及环境管家（检测 / 安装入参校验 /
默认打开方式识别与写入）。

自动截图（需要本机 Chrome）：

```powershell
cd frontend
node scripts/screenshot.mjs      # 主流程 13 张
node scripts/screenshot-light.mjs # 浅色主题
node scripts/shoot-env.mjs       # 环境管家 8 张（会真装一次 PHP，装完请在面板里卸载或手动 winget uninstall）
node scripts/check-env-ui.mjs    # 只做 UI 冒烟：确认环境面板渲染正常、无控制台报错
node scripts/check-image-input.mjs # 验证「粘贴 / 拖拽上传 + 点击放大预览」（会真的上传两张测试图）
node scripts/shoot-shots.mjs      # 会话截图占用 + 清理确认框 3 张
```

### 5.21 「为什么这么慢」：一轮演示的时间去哪了

拿出问题那一轮的真实落盘帧量了一下（316 帧 / 467 秒）：

| 指标 | 数值 |
| --- | --- |
| 相邻帧间隔中位数 | **0.6 秒** |
| 平均帧间隔 | 1.5 秒 |
| 超过 6 秒的帧 | 15 个（最长 11.8 秒） |

也就是说**循环本身不慢**，时间花在三个地方：

1. **视觉模型每次决策 7~12 秒**（送一张 1568×980 的图过去，躲不掉）；
2. **每一步还要再等 `interval_ms`（默认 2.8 秒）**，连 `wait 1 秒` 这种便宜动作也要等满；
3. **点空后的重试要干等 5 秒 + 10 秒** —— 一次没点中，15 秒就没了。

更糟的是这轮里连续 13 步都在点同一个 D 选项，全部打在**自家控制台窗口**上：
第 17 步它自己发现了「当前前台是屏幕演示控制台」，可那时已经废掉 13 步。

#### 三处改动

| 问题 | 改法 |
| --- | --- |
| 控制台挡住目标窗口 | `_make_room()`：动作执行前读前台窗口标题，命中「屏幕演示控制台」这类自家窗口就**自动最小化**，并把这一句写进提示词 |
| 点空后干等 15 秒 | `RETRY_DELAYS` 从 `(5.0, 10.0)` 改成 `(1.5, 3.0)`——多数"没变化"是点空了，不是加载慢 |
| `wait`/按键也要等满间隔 | `last_cheap_action` 标记：等待、按键、滚动、翻页之后，决策间隔压到 0.45 秒 |

顺带修了个小坑：模型写 `{"type":"focus"}` 不带标题时会被拒绝并报错，
现在会**默认切回本轮的演示目标**（`app_scope`）。

> 想整体更快就把控制台的「间隔」调小（比如 1200ms）：代价是给模型看清画面的时间变短。
> 但先修上面这三处更划算——它们省的是**白白浪费掉的十几秒**，不是思考质量。

---

### 5.20 勾选又自己取消、滚轮推不动：三个真因

测试答题时出现两个怪现象：**选项勾上了过一会儿又没了**、**滚轮滚半天页面不动**。
逐个查下来是三个独立问题：

#### ① 勾选框被反复点 → toggle 回去了

单选/多选的勾选框是 **toggle**：点一次选中，再点一次取消。
日志里第 1 题的 A 选项在 13 步内被点了 6 次，坐标还在漂
（`(256,848)`、`(250,921)`、`(256,832)`、`(243,792)`…），因为模型看不清勾选状态，
每次都"再确认一下"——结果每次确认都把上一次的勾去掉了。

修法（代码级，不靠提示词自觉）：
- `_note_repeat_click()`：记住最近 12 次点击点位；同一点 ±25（0~1000 坐标）内
  **3 步内来过**，就在这一步的结果里追加
  「⚠️ 这个位置第 N 步刚点过，再点一次就是**取消选中**——先确认它现在是勾上还是没勾」；
- `_loop_hint()`：同一块区域 3 次以上 → 往提示词里塞
  「疑似死循环：先用 zoom 放大确认勾选状态，**已选中的不要再点**」；
- 提示词补一条：勾选只点方框本身、**已选中的选项不要再点**。

#### ② 滚轮发给了错误的窗口

`pyautogui.scroll()` 把滚轮事件发给**光标底下**的窗口。之前的实现只在模型给了
x/y 时才移动光标；不给就原地滚——光标要停在控制面板、标题栏或某个不可滚动的
容器上，滚 10 下页面纹丝不动，日志里就是连续「滚动↓10 格」但画面不变。

修法：没给坐标时**先把光标移到画面中间偏下**（`width/2, height*0.55`）再滚；
滚完 `sleep(0.28)` 等平滑滚动动画结束，否则截到动画中间帧又会被判成"没变化"。

#### ③ 取证结果根本没进提示词（最要命的）

`runner.frame_context` 一路被 `append`，**却从来没有被渲染进 prompt**——
也就是说 `probe`（控件树/窗口清单）、`knowledge`、`web_search` 查到的内容，
模型一个都看不到，等于白查。这次一并接上了：

```
【本帧查到的外部信息】
【取证·controls】窗口「测验」共 42 个控件…
【查知识库·4P】命中：[0.82] 产品、价格、渠道、促销…
（这些是系统真实查到的，优先采信，别凭空猜）
```

> 三处都补了测试（重复点击提醒、死循环提醒、frame_context 能进 prompt），
> 全量 150 项通过。这个 bug 说明「新功能接上了」不等于「模型真的收到了」——
> 得拿真实 prompt 验一遍。

---

### 5.19 演示里也能联网查资料（答题救场）

屏幕演示原来只有三件"求助"手段：`zoom` 放大、`knowledge` 查本地库、`ask` 问用户。
本地库没课件时，遇到不认识的题就只能瞎猜或打断用户。补了两条联网动作：

```json
{"type":"web_search","query":"营销 4P 理论 产品 价格 渠道 促销"}
{"type":"web_open","url":"https://baike.baidu.com/item/4P"}
```

- 直接复用聊天侧的 `app/agent/tools/web.py`：Bing 优先、Sogou 兜底，12 秒超时，
  内网地址一律拒绝（防被诱导去扫本机）；
- 结果作为「取证」回到下一帧的提示词（和 `probe` / `knowledge` 同一条通道），最多 4 条摘要；
- 想细看某条再 `web_open` 读正文（截断 1600 字）；
- 联网失败会明确返回「先用自己的知识判断」，不让模型卡在重试上。

答题时的依据顺序也写进提示词了：

```
① knowledge 查本地知识库（有课件才灵）
② web_search 联网（看摘要够判断就判，不够再 web_open）
③ 都不行 → ask 让用户给答案
   绝不瞎猜——ask 永远比猜错便宜，用户就在电脑前
```

> 实测：`web_search` 能正常返回摘要（Bing 命中 3 条）；但搜索结果质量取决于措辞，
> 「营销 4P 理论 产品 价格 渠道 促销」比「市场营销 4P 是什么」靠谱得多——
> 所以提示词里让模型把题干里的关键词直接拼进 query，而不是整句话丢进去。

---

### 5.18 答题类页面：先答题再允许提交

测试「章节测验」时它**一道题没选就点了提交**，结果 0 分（超星这类平台不可重考）。
复盘：规划器把目标写成「完成测验并提交」，而屏幕侧的提示词里**没有任何答题规则**——
模型看到「提交」就当成了目标，滚动找按钮、点提交、确认，一气呵成。

#### 硬规则（写进屏幕侧 system prompt）

1. **绝对禁止空着提交**：还有题没选就不许点「提交 / 交卷 / 完成」，这一步不可撤销；
2. 提交前必须在 thought 里**逐题点名核对**：「已答：1 单选 B；2 单选 A；3 多选 ABD……4 题全部作答」；
3. **一题一动作**：读题干 → 想答案 → 点选项 → 读下一帧确认选中（圆点实心/方框打勾），不许一口气点一堆坐标；
4. 选项看不清先 `zoom` 放大；还不行就 `ask` 问用户，禁止"看不清就随便选"；
5. 课程特有的术语先查知识库（见下），查不到再 `ask`，不要瞎猜；
6. 多选少选也算错，提交前复查一遍；
7. 提交后出现红叉/低分**不要急着往下翻**：先记下错哪几题，`ask` 让用户决定（很多平台不给重考）。

规划器侧也补了一条：测验类任务**禁止**写成「完成测验并提交」一步到位，
必须拆成「读第 1 题」「为第 3 题（多选）勾选 A、B、D」…「全部答完后核对并提交」。

#### 新动作：查知识库

```json
{"type":"knowledge","query":"市场营销 4P"}
```

结果作为「取证」回到下一帧的提示词里（和 `probe` 同一条通道，不额外截图）。
**前提是知识库里真的有课件**：本机现在只有 18 篇编程知识，问「市场营销 4P」是 0 命中，
所以它会退化成「用自己的知识判断」。把课程资料传到「知识库」面板再演示，命中率才上得来。

> 实现笔记：检索必须放在主事件循环里 `await`，不能丢进 `asyncio.to_thread`——
> Qdrant 的异步客户端是绑事件循环的，跨线程 `asyncio.run` 会踩到 loop 不一致。

---

### 5.17 「画面明明变了却说没反应」到底是什么

排查一次真实演示（NEKOPARA，18 步）时，把落盘的截图逐帧算了一遍差异：

拿第二次演示（43 帧）按**逐像素**口径又量了一遍：

| 相邻两帧 | 真实变化像素 | 系统比例 | 判定 |
| --- | --- | --- | --- |
| 切窗口 | 94.5% | 0.973 | 有变化 |
| 一批「无变化」帧 | 0.006% ~ 0.063% | 0.00000 | 没变化（只有角落时钟在跳） |
| 文字真的换了一句 | **1.498%** | 0.0125 | **有变化** |

再把「无变化」那几帧的对话框区域裁出来并排看（`docs/screenshots/59-dialog-frames-compare.png`）：
连续 4 帧都还是“椰子「這種需要出力的工作就交給我吧。」”，直到第 5 帧才换成
“時雨「那紅豆就負責幫那三個包好的蛋糕綁上緞帶囉。」”——**文字确实一模一样**，
系统的判定没有错。

真正的病灶是**窗口没拿到焦点**：点一个非前台窗口的第一下只会“激活”，不会传到控件上，
而 `alt+tab` 靠猜顺序、`win+tab` 靠点缩略图，经常白折腾。所以新增了一个动作：

```json
{"type":"focus","title":"NEKOPARA"}     // 或 {"type":"focus","app":"nekopara_vold"}
```

用 `EnumWindows` 按标题/进程名找到窗口，再 `BringWindowToTop` + `SetForegroundWindow`
（先 `AttachThreadInput` 绕过前台锁），比按快捷键可靠得多；实测切换后
`GetForegroundWindow` 读回来的标题就是目标窗口。提示词里也写明了
「点在非前台窗口上的第一下只是激活窗口，前台变了就直接再来一次同样的点击」。
用户觉得"每次画面都不一样"，是因为**模型在看同一张图时描述出了不同的界面**
（同一帧先被说成"对话框文字稳定"，又被说成"标题界面"）——这才是要修的：

在提示词里显式告诉它画面状态：

```
【画面状态 · 重要】这一帧与上一帧像素完全相同（已连续 N 帧没变化）。
说明你上一步操作没有生效，而不是「画面变成了别的东西」。
所以：不要描述任何新出现的界面/文字，也不要重复上一次的动作。
```

计数来源是 `runner.same_frame_streak`（`ratio < 0.005` 连续累加，一变就归零）。

同时修了两个让"点不准"更严重的问题：

1. **光标被目标程序挪走**：实测某一步请求 (819,1216) 落到了 (825,1427)，偏移 211px。
   坐标换算本身没问题（本机实测 `moveTo` → `position()` 偏差 0），是游戏自己在挪光标。
   现在点完会核对落点，偏了**先回正一次**再判断，仍偏才在结果里提醒模型「这一下可能没点中」。
2. **重复动作被静默跳过**：被判过无效的动作，模型再选同样的坐标会被跳过执行（日志里是
   `[skipped]`），它就只能靠猜。现在提示词会告诉它"上一帧没变化、换做法"。

> 差异算法不变：64×40 灰度指纹 + 逐格阈值 6 + 全局 0.5% 比例。
> 用 44px 的真实字号验证过：换两行对话能到 **0.9%**（判定为"有变化"），
> 光标闪烁只有 **0.08%**（不会误判）。所以阈值不用改，缺的是"把结论告诉模型"。

---

### 5.16 演示中途提问：置顶小窗 + 答完真的会继续

屏幕演示的视觉模型遇到"选哪个"这类信息缺口时会停下来问。原来只有网页面板里的一行输入框，
演示进行时整屏都被别的程序占着（有时连控制面板自己都挡着），经常看不到；更糟的是**答完不动**。

#### ① 答完不动：回答被静默丢掉了

模型的 `ask` 动作会让演示循环 `return`（等回答），此时 `runner.task` 已结束。
学习者提交回答时 `resume()` 发现任务结束就走 `start()` → **新建一个 Runner**，
而答案原来只 append 在**旧 Runner** 的 `answers` 里 → 新 Runner 一条都不带 →
模型看到同一屏又原样问一遍，看起来就是"答了也没反应"。

修法：把回答与"已问过的问题"提到控制器层（`_answers` / `_asked`），
`start()` 建新 Runner 时接上；`stop()` 时清理。加回归测试
`tests/test_screen_ask.py::test_answer_is_kept_when_runner_restarts`。

顺带加了两条防线：

- **同一问题不重复打断**：已经问过且答过的问题再来一次 → 不弹窗，置 `force_act`，
  提示词里加「必须动手、禁止提问」，让模型直接执行；
- 提示词里加「别把自己的控制面板当成目标」：截图里出现「屏幕演示控制台」这类窗口时忽略它。

#### ② 置顶小窗：浏览器做不到，用 tkinter 开原生窗口

`app/screen_agent/ask_dialog.py` 是一个独立小进程（后端 `_spawn_ask_dialog()` 拉起）：

- `-topmost` 钉在最上层，属性里带问题、选项按钮（A/B）、输入框、提交
- 提交后 POST `/api/screen/sessions/{id}/answer`，后台收到就会跑起来
- 每 2 秒轮询会话状态：网页那边答掉了、或演示已结束 → 自己关掉
- 关窗（✕ / Esc）＝ 不作答，演示保持暂停

踩过的两个坑都写进代码注释了：

1. **窗口看不见**：后端用隐藏控制台的父进程拉起子进程，Windows 会让它继承
   `STARTUPINFO` 的 `SW_HIDE`，窗口建出来却是**最小化**状态（坐标 −32000）。
   所以创建后必须用 Win32 `ShowWindow(SW_SHOWNORMAL)` + `SetWindowPos(HWND_TOPMOST)` 强制显示；
2. **高 DPI 模糊**：不声明 DPI 感知时 Windows 把窗口位图放大 1.5 倍，字糊且坐标失真；
   启动时 `SetProcessDpiAwareness(2)` + `tk scaling` 按实际 DPI 缩放。

窗口高度按问题长短自适应（`update_idletasks` 后取 `winfo_reqheight`），
不然问题一长就把输入行挤出可视区。

> 开关：`.env` 里 `SCREEN_ASK_DIALOG=true/false`（默认开）。
> 截图：`docs/screenshots/58-ask-dialog-topmost.png`

---

### 5.15 截图会越攒越多，所以给每条对话显示占用并支持清理

屏幕演示每走一步就落盘 1~3 张 PNG（操作前 / 操作后 / 局部放大），一次 20 步的演示就是几十 MB。
项目自己的测试数据攒到过 **88 个演示会话 / 5268 张图 / 1.7 GB**，所以把「占多少、怎么删」做进了界面：

#### 占用的统计口径

| 落盘位置 | 归属判断 |
| --- | --- |
| `data/screenshots/<session_id>/` | 演示会话通过 `screen_sessions.conversation_id` 挂到聊天会话，目录大小算给那个会话 |
| `data/screenshots/shared/` | 「看一眼屏幕」工具抓的图没有会话目录，只能从消息内容里的 `/static/screenshots/shared/xxx.png` 反查；同一张图被多条消息引用只算一次 |

`GET /api/conversations` 一次返回每个会话的 `screenshot{bytes,images,sessions,human}` 和全库合计
（`screenshot_total` / `screenshot_orphans`）。目录大小按 mtime 做了缓存，首次约 400ms、之后 20ms 以内。

#### 三种删除方式

| 入口 | 接口 | 行为 |
| --- | --- | --- |
| 对话条目悬停 → 📷⊘ 图标 | `DELETE /api/conversations/{id}/screenshots` | **只删图**，聊天消息与演示步骤的文字记录保留，`screen_steps.screenshot` 置空（前端 `v-if` 挡住，不会裂图） |
| 删除对话 | `DELETE /api/conversations/{id}` | 截图 + 演示会话/步骤记录一起删（会话都没了，记录留着也没用） |
| 顶部 🧹 图标 | `DELETE /api/screenshots/orphans` | 清掉 `conversation_id` 为空、或指向已不存在会话的「孤儿演示」，以及没有任何消息引用的 shared 图 |

三种都会返回 `freed_bytes / freed_human`，前端弹 toast 告诉你省了多少。
确认框是自绘的（不是 `window.confirm`），并且**必须 `Teleport` 到 body**——
侧边栏有 `backdrop-filter`，会成为 `position: fixed` 的包含块，留在里面遮罩只盖住侧边栏、弹窗还会歪到左边。

> 命令行版本：`scripts/clean_screenshots.py --days 0 --keep-latest 5 --dry-run`（默认不删，加 `--yes` 才执行）。

—— 见 `docs/screenshots/51-conv-screenshot-size.png`、`52-conv-shot-hover.png`、`53-shot-cleanup-confirm.png`。

---

## 八、常见问题

**Q：没有 MySQL 能跑吗？**
能。`db_fallback_sqlite=true`（默认）时，MySQL 连不上会自动用 `data/code_mentor.db`，
表结构完全一致。想要严格 MySQL，用 `docker compose up -d mysql` 并改 `DATABASE_URL`。

**Q：为什么用 Qdrant 的 embedded 模式？**
它和 Qdrant 服务端是同一套引擎，只是把存储放在本地文件，省掉一个必须常驻的服务，
方便教学环境一键跑起来。要切服务端只需 `QDRANT_MODE=remote` + `QDRANT_URL`。

**Q：没有 API Key 怎么看效果？**
本地模型不需要 Key：装个 [Ollama](https://ollama.com/)，`ollama pull qwen3:8b`，然后在「模型接入 → Ollama 本地」
点一下就能用；也可以用任意 OpenAI 兼容端点（LM Studio / one-api / 学校网关）。
云端供应商里智谱的 `glm-4-flash` 有免费额度，是最省事的体验方式。

**Q：屏幕演示会真的动鼠标吗？**
会。所以默认提供「演练模式」（只识别不操作）和 `SCREEN_DRY_RUN=true` 开关；
运行中把鼠标移到屏幕左上角可触发 pyautogui 的 FAILSAFE 紧急中止。

**Q：模型列表里没有我要的模型（比如 DeepSeek 的 V4 系列）？**
点「模型接入」里的 **刷新模型列表**，它会实时请求该供应商的 `/models`，把你账户里真实可用的模型拉下来
（DeepSeek 账户目前返回 `deepseek-v4-pro`、`deepseek-flash` 等）。
列表里还是没有的话，直接在「对话模型」输入框里**手动填模型名**就能用 —— 这个字段本来就是自由输入。

**Q：测试连接成功了，但发消息说「还没有配置 API Key」？**
「测试连接」用的是输入框里的临时值，不落库。现在主按钮 **「保存并启用」** 会一步完成保存 + 切换，
测试连接成功时也会顺手保存你刚填的 Key；填了 Key 没保存时表单右上角会显示 `未保存` 标签。
若仍报错，多半是本地 `data/.fernet.key` 被替换过（旧密文解不开），重新填一次 Key 保存即可。

**Q：太黑了 / 想要白天主题？**
默认**跟随系统**（Windows 是浅色就自动用浅色主题）；右上角有 🌙/☀️ 一键切换，
也可以进「设置 → 运行参数 → 外观主题」固定为 浅色 / 深色 / 跟随系统。
选择存在浏览器本地（`localStorage.cm-theme`），下次打开自动生效。

**Q：中文输入是怎么打到屏幕上的？**
pyautogui 无法直接输入中文，这里用 Win32 API 写剪贴板 + `Ctrl+V` 粘贴。

---

## 九、交付物

- `backend/` 完整后端源码（含测试）
- `frontend/` 完整前端源码
- `docs/架构设计.md` 架构与数据模型说明
- `docs/验收对照表.md` 需求 → 实现 → 代码位置逐条对照
- `docs/视频讲解脚本.md` 录屏讲解脚本（含时间轴与讲解词）
- `docs/screenshots/` 57 张界面截图（深色 51 张 + 浅色 6 张）：主流程、供应商配置、外观与背景、屏幕演示、编辑器、环境管家 8 张（面板 / 折叠路径 / 卡片 / 手动安装弹窗 / 二次确认弹窗 / 阶段进度 / 装完 / 编辑器库）、初始包实拍 1 张
- `scripts/` 一键启动、冒烟测试、自动截图、打「初始版」发布包（`build_release.py`）
- `release/CodeMentor-1.0.0-initial.zip` 初始版发布包：默认 logo/名称、预置知识库与最优参数、无对话与记忆（可随时重新生成）

---

<p align="center"><sub>Made for 人工智能课程作业 · 编程学习助手</sub></p>
