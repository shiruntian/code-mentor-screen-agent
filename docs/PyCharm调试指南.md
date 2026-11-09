# 在 PyCharm 里调试 CodeMentor

工程里已经放好 4 个运行配置，**打开项目后右上角下拉框直接能选**：

| 配置 | 用途 |
| --- | --- |
| 后端 · 调试 uvicorn (8000) | 带断点调试后端（**不带 --reload**） |
| 后端 · 热重载运行 (8000) | 平时开发，改代码自动重启 |
| 后端 · 全部测试 | 跑 `backend/tests`（249 项） |
| 前端 · vite dev (5173) | 前端热更新开发 |

> 配置放在 `.idea/runConfigurations/`。`.idea/` 在 `.gitignore` 里，所以这些配置**只在你本机生效**，
> 不会进仓库；要共享的话得单独把 `runConfigurations` 挪出版本库忽略。

## 一、第一次打开项目

1. **解释器**：`File → Settings → Project → Python Interpreter → Add Interpreter → Existing`
   选 `backend\.venv\Scripts\python.exe`（工程里已经配好，一般会自动识别）。
2. 确认 `Settings → Build, Execution, Deployment → Python Debugger` 里
   **不要勾** “Gevent compatible”（勾了协程断点会错乱）。
3. 右上角选择 **后端 · 调试 uvicorn (8000)** → 点虫子图标 🐞。

启动后控制台应该看到：

```
启动 CodeMentor · 编程学习助手 v1.0.0
MySQL 数据库就绪: code_mentor
Qdrant 使用本地 embedded 模式: ...\data\qdrant
服务就绪: http://127.0.0.1:8000  (文档 /docs)
```

## 二、调试前必须清场

三个东西会抢资源，报错信息都很隐晦：

| 冲突 | 现象 | 处理 |
| --- | --- | --- |
| 8000 端口被占 | `[Errno 10048] address already in use` | 先停掉别的后端（含 `start.bat` 起的、或之前挂着的进程） |
| Qdrant 本地库锁 | `Storage folder ... is already accessed by another instance` | 同上：同时只能有一个后端进程持有 `data/qdrant` |
| MySQL 没起 | `MySQL 连接失败，回落到 SQLite` | 启动 MySQL 服务；或用 SQLite 也能跑（`DB_FALLBACK_SQLITE=true`） |

查占用：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
```

## 三、断点打在哪

| 想调什么 | 文件 | 函数 |
| --- | --- | --- |
| HTTP 接口 | `backend/app/api/routes/*.py` | 各 `@router.post/get` 函数 |
| 对话链路（LangGraph） | `backend/app/agent/graph.py` | `plan` / `act` 相关节点 |
| 屏幕演示主循环 | `backend/app/screen_agent/controller.py` | `ScreenController._loop` |
| 一次决策（发给模型的完整提示词） | 同上 | `_decide` |
| 动作执行 / 判卷 | 同上 | `_execute_action` / `_judge_previous` |
| 截图与像素判断 | `backend/app/screen_agent/capture.py` | `find_marks` / `crop_region` |

### 调试屏幕演示的两个注意点

1. **断点会把整个事件循环冻住**：屏幕演示跑在后端进程里，停下时网页会卡住、鼠标也停。
   看完按 `F9` 继续。中断太久的话，前端的 SSE 可能超时断线（刷新页面即可）。
2. **想看又不打断，用「不挂起断点」**：右键断点 → 取消 `Suspend` → 勾上 `Evaluate and log`，
   填 `action, thought` 之类。它只往控制台打日志，演示照常跑。
   调 `_loop` 这种每帧都过的循环时，这个比普通断点好用得多。

## 四、前端

两种方式：

- **只调后端**：直接用 `http://127.0.0.1:8000`（后端会把 `frontend/dist` 当静态站发），
  改前端代码需要重新 `npm run build`。
- **前后端一起调**：先跑「前端 · vite dev (5173)」，再跑后端；Vite 已配好
  `/api` → `http://127.0.0.1:8000` 代理，浏览器开 `http://127.0.0.1:5173`。

## 五、调试测试

`backend/tests` 下随便一个测试函数左边有绿色三角，右键 **Debug 'test_xxx'** 即可；
想跑全部就选「后端 · 全部测试」。

命令行等价写法：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q          # 全部
.\.venv\Scripts\python.exe -m pytest tests/test_screen_marks.py -q -k blue
```

## 六、常见坑

| 现象 | 原因 / 处理 |
| --- | --- |
| `ModuleNotFoundError: app` | 工作目录不是 `backend`。运行配置里已经设成 `$PROJECT_DIR$/backend` |
| 日志中文乱码 | 加环境变量 `PYTHONIOENCODING=utf-8`（配置里已加） |
| 断点不生效 | 用了 `--reload`：调试进程和实际工作进程不是同一个。调试配置**故意不带** reload |
| 改了代码没反应 | 用的是「调试」配置（无 reload），重启一下，或改用「热重载运行」 |
| 屏幕演示点了没反应 | 后端进程需要有交互桌面权限（在服务/计划任务里跑会拿不到桌面） |
| 想让它读网页 DOM | 用 `scripts/open-edge-debug.bat` 起浏览器（带 `--remote-debugging-port=9222`） |