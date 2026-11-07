"""内置知识包：首次启动自动入库，保证 RAG 开箱即有内容可检索。

内容为原创整理，覆盖 Python / FastAPI / Vue / 数据库 / 工程实践等常见学习主题。
"""

from __future__ import annotations

from typing import Any

SEED_DOCS: list[dict[str, Any]] = [
    {
        "title": "Python 装饰器：从函数是一等对象讲起",
        "source": "内置知识包 / Python 进阶",
        "tags": "python,装饰器,闭包",
        "content": """# Python 装饰器

## 核心前提
Python 里函数是「一等对象」：可以赋值给变量、作为参数传递、作为返回值返回。
装饰器本质上就是「接收函数、返回新函数」的高阶函数。

## 最小实现

```python
import functools

def log_calls(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        print(f"调用 {func.__name__}，参数={args} {kwargs}")
        result = func(*args, **kwargs)
        print(f"{func.__name__} 返回 {result}")
        return result
    return wrapper

@log_calls
def add(a, b):
    return a + b
```

`@log_calls` 等价于 `add = log_calls(add)`。

## 带参数的装饰器
需要三层嵌套：最外层收装饰器参数，中层收函数，内层收调用参数。

```python
def retry(times=3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if i == times - 1:
                        raise
        return wrapper
    return decorator
```

## 常见坑
1. 忘记 `functools.wraps`，导致函数名、docstring 丢失。
2. 装饰器在「导入时」执行，不是调用时；初始化逻辑不要写太重。
3. 装饰顺序自下而上：`@a` 在 `@b` 上方时等价于 `a(b(func))`。
4. 类方法装饰时注意 `self` 的位置。

## 练习
1. 写一个 `@timer` 统计函数耗时。
2. 写一个 `@cache` 用字典缓存结果，并与 `functools.lru_cache` 对比。
""",
    },
    {
        "title": "Python 虚拟环境与依赖管理（venv / pip / uv）",
        "source": "内置知识包 / 环境配置",
        "tags": "python,venv,pip,uv,环境",
        "content": """# 虚拟环境与依赖管理

## 为什么需要
不同项目依赖的包版本可能冲突。虚拟环境为每个项目隔离一套 `site-packages`，
避免「装了一个包，另一个项目崩了」。

## 标准库 venv

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS / Linux
source .venv/bin/activate

python -m pip install --upgrade pip
```

退出：`deactivate`。

## pip 常用命令

```bash
pip install requests
pip install "fastapi>=0.115"
pip freeze > requirements.txt
pip install -r requirements.txt
pip list --outdated
```

## uv：更快的现代选择

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
```

uv 基于 Rust 实现，解析依赖和下载都明显更快，命令与 pip 基本兼容。

## 常见报错
- `ModuleNotFoundError: No module named 'xxx'`：装到了别的解释器 / 没激活虚拟环境。
- `pip` 版本过旧导致解析超时：先 `python -m pip install -U pip`。
- 国内网络慢：配置镜像 `pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple`。

## 排查顺序
1. `where python`（Windows）/ `which python` 确认解释器路径。
2. `python -c "import sys; print(sys.executable)"` 确认当前解释器。
3. `pip show 包名` 看安装位置。
""",
    },
    {
        "title": "FastAPI 入门：路由、模型校验、依赖注入",
        "source": "内置知识包 / Web 后端",
        "tags": "fastapi,python,web,api",
        "content": """# FastAPI 快速入门

## 最小应用

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Demo")

class Item(BaseModel):
    name: str
    price: float

@app.post("/items")
def create_item(item: Item):
    return {"ok": True, "item": item.model_dump()}
```

启动：`uvicorn main:app --reload`，文档在 `/docs`。

## 请求参数的四种来源
- 路径参数：`@app.get("/items/{item_id}")` 的 `item_id`
- 查询参数：函数签名里带默认值的普通参数
- 请求体：Pydantic 模型
- 请求头：`Header(...)`，或自定义依赖

## 依赖注入

```python
from fastapi import Depends

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/users")
def list_users(db = Depends(get_db)):
    ...
```

依赖可以是函数、类或生成器；生成器写法适合管理数据库连接这类需要释放的资源。

## 异步注意点
- `async def` 里不要写阻塞调用（`requests`、`time.sleep`），会卡住事件循环。
- 阻塞库可以用 `run_in_threadpool` 或直接写 `def`（FastAPI 会自动放进线程池）。

## 流式响应
SSE 用 `StreamingResponse`，`media_type="text/event-stream"`，每条消息以 `data: xxx\\n\\n` 结尾。
""",
    },
    {
        "title": "Vue3 组合式 API 与响应式原理",
        "source": "内置知识包 / 前端",
        "tags": "vue,vue3,前端,响应式",
        "content": """# Vue3 组合式 API

## ref 与 reactive
- `ref(0)`：包装任意值，用 `.value` 读写模板里自动解包。
- `reactive({})`：只能用于对象，直接属性访问。
- 解构 `reactive` 对象会丢失响应性，需要 `toRefs`。

```js
import { ref, computed, watch } from 'vue'

const count = ref(0)
const double = computed(() => count.value * 2)
watch(count, (val) => console.log('变了', val))
```

## 生命周期
`onMounted`、`onUnmounted`、`onUpdated` 等都要在 `setup` 同步阶段调用。

## 响应式原理
Vue3 使用 `Proxy` 拦截 get/set：get 时收集依赖（track），set 时触发更新（trigger）。
相比 Vue2 的 `Object.defineProperty`，可以监听新增属性、数组下标和 Map/Set。

## 组件通信
- props 向下、emit 向上
- `defineModel()` 简化 v-model
- provide/inject 跨层级
- Pinia 做全局状态

## 性能建议
1. 大列表用 `v-memo` 或虚拟滚动。
2. 避免在模板里写复杂表达式，提到 computed。
3. 频繁变化的深层对象慎用 `deep: true` 的 watch。
""",
    },
    {
        "title": "Python 常见报错排查手册",
        "source": "内置知识包 / 排错",
        "tags": "python,报错,异常,debug",
        "content": """# 常见报错速查

## TypeError: 'NoneType' object is not subscriptable
对象是 `None`。往上一层找「为什么没返回东西」：函数忘了 `return`、数据库查询没命中、
字典 `.get()` 返回默认值。

## KeyError: 'xxx'
字典没有这个键。用 `d.get(key, default)` 或 `collections.defaultdict`。
如果是解析 JSON，先打印原始结构确认层级。

## IndentationError / TabError
缩进混用了 Tab 和空格。统一改成 4 个空格；编辑器底部打开「显示空白字符」。

## ModuleNotFoundError
1. 确认虚拟环境已激活。
2. `python -c "import sys; print(sys.executable)"` 看解释器。
3. 本地包要 `pip install -e .`。

## ValueError: too many values to unpack
解包数量不匹配。打印对象长度，或改用 `*rest` 收集剩余值。

## 循环导入 ImportError
两个模块互相 import。解决办法：
- 把 import 移到函数内部（延迟导入）
- 抽出第三个模块放公共类型
- 用 `TYPE_CHECKING` 只做类型标注导入

## 万能排查法
1. 读完整 traceback，**从最后一行往前**看调用链。
2. 最小复现：删到只剩报错的那几行。
3. 打印中间变量的 `type()` 与 `repr()`。
4. 用 `python -m pdb script.py` 或编辑器的断点。
""",
    },
    {
        "title": "算法复杂度速查与常见误区",
        "source": "内置知识包 / 算法",
        "tags": "算法,复杂度,数据结构",
        "content": """# 时间复杂度速查

| 操作 | 平均 | 说明 |
| --- | --- | --- |
| 列表索引 | O(1) | 连续内存 |
| 列表 `in` | O(n) | 线性扫描 |
| 字典 / 集合查找 | O(1) | 哈希，最坏 O(n) |
| 列表尾部 append | O(1) 摊还 | 扩容时 O(n) |
| 列表头部 insert(0) | O(n) | 需要整体搬移，改用 deque |
| 排序 | O(n log n) | Timsort |

## 空间复杂度
递归调用栈也算空间。深度为 n 的递归是 O(n) 空间，容易栈溢出。

## 常见误区
1. **二层循环不一定 O(n²)**：内层若是指数收缩（如 `i *= 2`），是 O(n log n)。
2. **字符串拼接**：`s += x` 在循环里是 O(n²)，改用 `''.join(list)`。
3. **`list.pop(0)`** 是 O(n)，队列请用 `collections.deque`。
4. **只看最坏情况**：哈希表最坏 O(n)，但工程上通常按平均算。

## 写代码前的三步
1. 估算数据规模：n 到 1e5 时 O(n²) 会超时。
2. 选对数据结构：查重用 set，频繁首尾操作用 deque，有序用 bisect。
3. 先写对再优化，用 `time.perf_counter()` 实测。
""",
    },
    {
        "title": "Git 基础工作流与常见事故处理",
        "source": "内置知识包 / 工程实践",
        "tags": "git,版本控制,协作",
        "content": """# Git 基础工作流

## 日常四步

```bash
git status                 # 看改了什么
git add -A                 # 暂存
git commit -m "feat: xxx"  # 提交
git push origin main       # 推送
```

## 分支
```bash
git switch -c feature/login   # 新建并切换
git switch main               # 切回
git merge feature/login       # 合并
```

## 查看历史
```bash
git log --oneline --graph --all
git diff            # 工作区 vs 暂存区
git diff --staged   # 暂存区 vs 上次提交
```

## 常见事故
- **改错文件想撤销**：`git restore 文件名`（未 add）或 `git restore --staged` 后再 restore。
- **提交信息写错**：`git commit --amend -m "新信息"`（仅限未推送）。
- **误删分支**：`git reflog` 找到 hash，再 `git branch 名字 hash`。
- **冲突**：编辑冲突文件保留正确内容 → `git add` → `git commit`。

## .gitignore 要点
忽略虚拟环境、缓存、密钥：
```
.venv/
__pycache__/
.env
data/
node_modules/
```

永远不要把 API Key 提交到仓库；一旦提交，即使删除历史也已被记录，应立即吊销该 Key。
""",
    },
    {
        "title": "RAG 与向量数据库：从原理到落地",
        "source": "内置知识包 / AI 应用",
        "tags": "rag,qdrant,向量,检索,embedding",
        "content": """# RAG（检索增强生成）

## 为什么需要 RAG
大模型的知识有截止时间，也不了解你的私有资料。RAG 在提问时先检索相关片段，
把片段塞进提示词，让模型「看着资料回答」，显著降低幻觉。

## 四步流水线
1. **切分（Chunking）**：按标题/段落切成 300~800 字的块，块间保留少量重叠，
   避免把一句话切成两半。代码块要整体保留。
2. **向量化（Embedding）**：把文本编码成定长向量，语义相近的向量距离更近。
3. **入库（Index）**：写入向量数据库（本项目用 Qdrant），附带原文与来源元数据。
4. **检索（Retrieve）**：把问题向量化，做相似度搜索，取 Top-K 片段拼进提示词。

## 混合检索
纯向量对「专有名词、错误码」不敏感，工程上常用「向量召回 + 关键词/BM25 重排」，
本项目的知识库检索就是这样做的：向量相似度占 0.62，关键词重合度占 0.38。

## Qdrant 关键概念
- Collection：一组向量，创建时指定维度与距离度量（Cosine）。
- Point：id + vector + payload，payload 存原文和元数据。
- Filter：按 payload 过滤，例如只检索某个文档。

## 效果优化清单
1. 切分粒度先调好，再谈换模型。
2. 保留来源，让答案可追溯。
3. Top-K 不要贪多，3~6 条通常够用，太多会稀释注意力。
4. 加一句「若资料中没有答案，请说明不知道」，能明显减少编造。
""",
    },
    {
        "title": "Python 异步编程：async/await 与事件循环",
        "source": "内置知识包 / Python 进阶",
        "tags": "python,异步,asyncio,并发",
        "content": """# 异步编程要点

## 适用场景
I/O 密集（网络请求、数据库、文件）用 async 收益大；
CPU 密集（大量计算）应该用多进程，async 不会变快。

## 基本写法

```python
import asyncio

async def fetch(name, delay):
    await asyncio.sleep(delay)
    return f"{name} done"

async def main():
    results = await asyncio.gather(
        fetch("a", 1), fetch("b", 2), fetch("c", 1)
    )
    print(results)

asyncio.run(main())
```

## 三个高频坑
1. **忘了 await**：`coro()` 只创建协程对象，不执行，还会报 "never awaited"。
2. **在协程里调用阻塞函数**：`time.sleep`、`requests.get` 会卡死整个事件循环，
   用 `asyncio.to_thread()` 或换异步库（httpx / aiohttp）。
3. **CPU 密集任务**：改用 `concurrent.futures.ProcessPoolExecutor`。

## 超时与取消
```python
try:
    await asyncio.wait_for(slow_task(), timeout=5)
except asyncio.TimeoutError:
    print("超时")
```

## 与线程的关系
一个事件循环跑在一个线程里；协程切换由代码显式 `await` 让出，开销远小于线程切换。
""",
    },
    {
        "title": "MySQL 索引与慢查询基础",
        "source": "内置知识包 / 数据库",
        "tags": "mysql,sql,索引,数据库",
        "content": """# MySQL 索引基础

## B+ 树索引
InnoDB 用 B+ 树：非叶子节点只存键，叶子节点存数据并用链表相连，
所以既能快速等值查找，也能高效范围扫描。

## 最左前缀原则
联合索引 `(a, b, c)` 能命中 `a`、`a+b`、`a+b+c` 的查询，
单独查 `b` 用不上索引。

## 让索引失效的写法
1. 在索引列上做函数/运算：`WHERE YEAR(created_at)=2024`。
2. 隐式类型转换：字符串列用数字比较。
3. `LIKE '%关键字'` 前置通配。
4. `OR` 连接未建索引的列。

## 排查慢查询
```sql
EXPLAIN SELECT * FROM messages WHERE conversation_id = 'abc' ORDER BY id DESC;
```
重点看 `type`（`ALL` 全表扫描要警惕）、`key`（实际用的索引）、`rows`（预估扫描行数）。

## 分页优化
深分页 `LIMIT 100000, 20` 很慢，改用游标：
```sql
SELECT * FROM messages WHERE id > 100000 ORDER BY id LIMIT 20;
```

## 设计建议
- 主键用自增整数或有序 UUID，避免随机写放大。
- 高频过滤列建索引，但索引不是越多越好，写入会变慢。
- 大文本（文章正文）单独放表或对象存储。
""",
    },
]