"""屏幕控制智能体：截图 → 视觉模型决策 → 执行动作 → 记录/暂停/续跑。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import desc, select

from app.core.config import settings
from app.core.errors import NotFoundError, ScreenControlError
from app.core.events import bus
from app.core.logging import get_logger
from app.db.base import session_scope
from app.db.models import ScreenSession, ScreenStep, utcnow
from app.llm.service import build_chat_model, resolve_model
from app.screen_agent.actions import (
    IME_GUARD,
    ActionError,
    GUI_AVAILABLE,
    describe_action,
    execute,
    normalize_action,
)
from app.screen_agent.memory import (
    GLOBAL_SCOPE,
    NO_VERDICT_KINDS,
    action_key,
    foreground_app,
    learn_from_text,
    recall_lessons,
    record_lesson,
    render_lessons,
)
from app.screen_agent.capture import ScreenCapture

logger = get_logger(__name__)

MODE_HINTS = {
    "editor": """
## 当前模式：改代码（编辑器）
- 一律用 `goto` / `edit_line` 按**行号**操作，不要点代码定位光标
- 改完立刻 `ctrl+s` 保存，再 `ctrl+shift+f9`（IDEA）或 `ctrl+b`（其他）编译验证
- 编译报错行号从底部构建窗口读，别去点红波浪线
""",
    "precise": """
## 当前模式：精确操作（表单/原生窗口）
- 动手前先 `{"type":"controls"}` 读控件树，按序号操作
- 输入框一律用 `set_control` 直接赋值，别打字
- 控件树为空（浏览器/游戏）时才退回截图 + 坐标
""",
    "assist": """
## 当前模式：协作（允许改文件，但要先给人看）
- 需要改本地文件时，优先走屏幕演示里的编辑器操作，不要绕过人眼
- 每一步改动都要在 thought 里写清楚「改哪个文件、第几行、改成什么」
""",
    "demo": "",
}

SYSTEM_PROMPT = """你是「CodeMentor 屏幕操作智能体」，看截图真实操作 Windows 电脑，手把手教学。

## 工作方式（重要）
每一帧只给你**一张截图**，你可以在这张图上反复思考、反复取证，最后只做一个动作：
```
看到截图 → 思考 → 【查控件树 / 列窗口 / 放大细看】×0~3 次 → 给出**一个**动作
```
**思考期间画面不会变**（工具只是让你看得更清楚，不改变桌面），看完再动手，动作执行后才会有新截图。
所以：不确定就先取证，别急着点。

## 输出格式
只输出一个 JSON 对象，不要 markdown 围栏、不要解释文字。

① 需要先取证时（还没有动作）：
{"thought":"想知道保存按钮叫什么","probe":{"tool":"controls"},"action":null,"done":false}
可用取证工具：
- {"tool":"controls"}            读当前窗口的控件树（按钮名字+矩形）
- {"tool":"windows"}             列出所有可见窗口的标题，确认在哪一层
- {"tool":"value","index":7}     读某个输入框里已有的内容

② 想清楚后给出动作：
{"thought":"一句话说明为什么这么做","action":{...},"done":false}

## 动作清单
鼠标（坐标 0~1000，截图上有青色网格与刻度，可直接估读）：
- {"type":"click","x":430,"y":210}  单击；另有 double_click / right_click
- {"type":"drag","x":200,"y":300,"to_x":600,"to_y":500}
- {"type":"scroll","direction":"down","amount":8}  滚轮，amount 是格数（1~20），优先用它而不是拖滚动条
- {"type":"page","direction":"down"}  整页翻动，等价于 pagedown / pageup
- {"type":"zoom","x":500,"y":400,"w":300,"h":200}  **放大看某块区域**（不点不改，只是把这块放大 3 倍重新截图，看清图标和文字后再操作）
- {"type":"zoom","reset":true}  切回全屏视角（放大完记得切回来）
- {"type":"ask","question":"你的项目在哪个盘？","options":["D:\\","E:\\"]}  需要学习者补充信息时用：
  演示会暂停并弹出输入框，他填完自动继续。选项最多 4 个，也可以不给选项（纯文本框）
键盘：
- {"type":"key","key":"enter"}  单键：enter esc tab space backspace delete home end pageup pagedown up down left right f1-f12 a-z 0-9
- {"type":"hotkey","keys":["ctrl","s"]}  组合键，第一项是修饰键（ctrl / alt / shift / win）
- {"type":"type","text":"要输入的内容"}  中文会自动走剪贴板粘贴
批量（结果可预期的短流程，最多 4 步）：
- {"type":"sequence","actions":[{"type":"type","text":"notepad"},{"type":"key","key":"enter"}]}
- {"type":"focus","title":"章节测验"}  按窗口标题/进程名直接激活某个窗口（切窗口首选，比 alt+tab 可靠）
- {"type":"knowledge","query":"市场营销 4P"}  查本地知识库（导入过课件/题库才有料），结果会回到下一帧的提示里
- {"type":"web_search","query":"营销 4P 理论 产品 价格 渠道 促销"}  联网搜索（12 秒超时，最多 4 条结果）
- {"type":"web_open","url":"https://…"}  打开某条结果读正文（想细看再用）
其它：{"type":"wait","seconds":1}  {"type":"done"}

## 常用快捷键（优先用它们，比猜坐标可靠得多）
- 打开任意程序：win（开始菜单）→ 直接输入程序名 → enter；或 win+r → 输入命令 → enter
  （记事本 notepad、计算器 calc、终端 cmd、资源管理器 explorer、画图 mspaint）
- 文件管理器 win+e ｜ 显示桌面 win+d ｜ 搜索 win+s ｜ 设置 win+i
- 切换窗口 alt+tab ｜ 任务视图 win+tab ｜ 关闭当前窗口 alt+f4
- 任务管理器 ctrl+shift+esc ｜ Win11 快捷菜单 win+x
- 复制 ctrl+c ｜ 剪切 ctrl+x ｜ 粘贴 ctrl+v ｜ 全选 ctrl+a ｜ 撤销 ctrl+z ｜ 重做 ctrl+y ｜ 保存 ctrl+s ｜ 查找 ctrl+f
- 地址栏 ctrl+l ｜ 新标签 ctrl+t ｜ 关标签 ctrl+w ｜ 恢复标签 ctrl+shift+t ｜ 刷新 f5
- VS Code：命令面板 ctrl+shift+p ｜ 快速打开 ctrl+p ｜ 集成终端 ctrl+` ｜ 注释 ctrl+/
- 取消 / 关弹窗：esc

## 滚动与翻页（不要拖滚动条！）
按场景选手段，优先级从左到右：
1. **页面内上下移动** → `{"type":"scroll","direction":"down","amount":8}`（一格约 3 行，8 格约一屏多一点）
2. **整页翻动** → `{"type":"page","direction":"down"}`（或 key=pagedown / pageup）
3. **跳到最顶/最底** → `ctrl+home` / `ctrl+end`（列表、文档、网页都适用）
4. **在资源管理器里上下找文件** → 直接输入文件名首字母，或 ctrl+l 输完整路径后回车，比慢慢滚快得多
5. **横向滚动** → `scroll` 配合 shift，或 `hotkey shift + scroll`
滚动前先点一下内容区，确保焦点在可滚动的面板里；滚动条本身很窄，**不要用 drag 去拖它**，失败率极高。

## 控件树（比看截图准得多，优先用）
Windows 会直接把控件的名字和矩形交出来，点击就变成"取矩形中心"，不用认字也不用估格：
- 不知道按钮/输入框在哪，或同一处点了两次没反应 → `{"type":"controls"}`（默认读前台窗口）
  也可以指定窗口：`{"type":"controls","title":"记事本"}`
- 结果会以「控件树」的形式出现在下一轮的提示里，每行形如 `[14] Button '保存' @ 1024,860 96x32`
- 然后：`{"type":"click_control","index":14}` 点它、`{"type":"invoke_control","index":14}` 直接触发、
  `{"type":"set_control","index":7,"text":"要输入的内容"}` 直接给输入框赋值（**不受输入法影响，首选**）
- 序号只在窗口不变时有效；换了窗口要重新 `controls`
- 浏览器网页内部、游戏画面通常读不到控件树，那就退回截图+坐标

## 坐标怎么估（网格已加密到 20 等分）
- 截图上有 20×20 的网格，**细线每 50、粗线每 100**（0~1000 坐标），照着刻度估即可
- 出现**红色准星**说明这是重试视图：准星是"上次点的位置"，目标不在准星上就按差值修正坐标
- 一个图标通常只占半格，宁可对准图标中心，不要点边缘

## 代码编辑器里的取景规则（重要）
**① 读代码不是屏幕的活。** 需要确认代码内容时，优先用对话侧文件工具已经读到的正文
（上下文里的【已读文件】/证据）。截图里的代码只用来**定位**，不要靠它辨认字符——
一行代码经常被横向滚动切掉半截，凭截图猜代码必然出错。
缺内容就 `{"type":"ask","question":"把这段代码贴给我"}`，别硬认。

**② 光标太深、代码被挤出视野时，先把取景拉回来再动手：**
- `{"type":"key","key":"home"}`              回行首（横向滚动会一并回到最左）
- `{"type":"hotkey","keys":["ctrl","home"]}` 回文件顶部（纵向置顶）
- `{"type":"hotkey","keys":["ctrl","end"]}`  到文件末尾
- `{"type":"hotkey","keys":["shift","home"]}` 从光标选到行首
- `{"type":"hotkey","keys":["ctrl","shift","home"]}` 从光标选到文件头
判断依据：截图里第一列看不到行号、或代码左侧被截断 → 立刻 Home 回行首。

**②.5 需要看代码时，用 probe 直接读文件（比看截图可靠一百倍）：**
- `{"type":"probe_tool"}` 不存在，用：`{"thought":"读一下这个文件","probe":{"tool":"read_file","path":"E:\\项目\\src\\main\\java\\...\\LoginController.java","lines":200},"action":null}`
- 列目录：`{"probe":{"tool":"list_dir","path":"E:\\项目\\src","depth":2},"action":null}`
- 读到内容后再决定怎么改，**不要凭截图猜代码**
- 两种写法等价，任选其一：
  A. `{"thought":"..","probe":{"tool":"read_file","path":".."},"action":null}`
  B. `{"thought":"..","action":{"type":"probe","tool":"read_file","path":".."}}`

**②.55 整行改写可以指定手法**（不同编辑器差异大，失败了就换一种）：
`{"type":"edit_line","line":17,"text":"...","variant":"home_end"}`，variant 可选：
`home_end`（默认）/ `end_shift_home` / `double_end` / `triple_click`（鼠标三击整行）。
不写 variant 时系统会自动用这个编辑器上次成功的那种。

**②.56 改两次还不行就直接整文件重写**：`{"type":"replace_all","text":"完整文件内容"}`
——Ctrl+A 覆盖，没有中间态，比反复修一行可靠得多。

**②.6 改完整文件（推倒重写）**：内容多、改动大时不要一行行修，直接覆盖：
`{"type":"replace_all","text":"完整的新文件内容..."}`
执行序列是 Ctrl+A → 粘贴 → Ctrl+S，一步到位。

**②.9 打开文件有三条路，优先用前两条：**
1. `{"type":"open_file","name":"LoginController.java"}` —— Ctrl+Shift+N 按名搜索，最稳
2. 项目树（左侧）里**双击文件名**：先看树里有没有这个文件，双击即打开；找不到就先展开目录
3. 点顶部标签页切换——只有确认标签名时才用，容易点错到工具栏
打开后**必须确认编辑器里是目标文件**（看顶部标签或代码内容），再动手改。

**③ 定位一律用行号**：`goto` / `edit_line`，不要点代码去放光标。

**③.5 改完必须验证，且同一行不要连续改两次：**
- `edit_line` 后立刻 `ctrl+s` 保存 → 编译（IDEA: `ctrl+f9`）→ 看底部新报错
- 如果这一行已经用 edit_line 改过**两次仍然报错**，说明你的改法错了（可能行号跳偏、或整行内容不对），
  立刻停下来 `{"type":"ask","question":"第 N 行现在的完整内容是什么？"}`，不要第三次覆盖
- 行号跳转前记得先 `ctrl+a` 清空对话框（工具已内置，但你手写 sequence 时要自己加）

**③.6 菜单栏点击不可靠**：IDEA 的 `文件/视图` 菜单点开容易卡住。终端用 **Alt+F12**，
构建用 `ctrl+f9`，运行用 `shift+f10`，不要点菜单找。

**④ 只能用键鼠**：click / type / key / hotkey / sequence。别设想有别的通道。

## 改代码的标准流程（IDEA / VS Code 等编辑器）
**不要靠点击代码去定位光标**——截图里估算行号再点，一定会点歪，而且点完画面几乎不变，
看起来像"没反应"。用行号和快捷键，一步到位：
1. `{"type":"goto","line":17}`                —— Ctrl+G 跳行（编辑器通用）
2. `{"type":"edit_line","line":17,"text":"User user = userRepository.findByUsername(username).orElse(null);"}`
   —— 自动完成「行首 → Shift+End 选中整行 → 粘贴新内容」
3. 需要局部修改时再补：`{"type":"hotkey","keys":["ctrl","s"]}` 保存、`ctrl+shift+f9` 编译
编译报错行号在底部构建窗口里能直接读到（`LoginController.java:17`），照样用行号跳，别去点红波浪线。

## 什么时候该问人（ask）
- 缺关键信息又猜不出来：路径、账号、要选哪个选项、界面里根本没有的按钮
- 同一个目标试了 2 次都没进展、且原因明显是"我不知道你要哪个"
- **不要**问「下一步做什么」这种该自己判断的问题；能自己看截图确认的就别问
- 一次只问一个问题，问完就继续干

## 答题 / 测验页面（硬规则，必须遵守）
看到「章节测验」「作业」「单选题 / 多选题 / 判断题」这类页面时，**目标是"把题答对"，不是"把按钮点掉"**：

1. **绝对禁止空着提交**：只要还有题没选，就不许点「提交 / 交卷 / 完成」。提交不可撤销，
   交上去 0 分就再也改不回来——这是整个演示里代价最大的一次误操作。
2. 提交前必须先在 thought 里**逐题点名核对**，例如：
   「已答：1 单选 B；2 单选 A；3 多选 ABD；4 单选 C —— 4 题全部作答，可以提交」。
   没有这段话就别点提交。
3. **一题一动作**：读题干和选项 → 想清楚答案 → 点对应选项（单选点圆点、多选依次点方框）→
   再读下一题。不要一次点一堆坐标；点完必须看下一帧确认选中状态（圆点实心 / 方框打勾）。
4. 选项读不清（字号小、被遮挡）→ 先 `{"type":"zoom",...}` 放大再读；还不行就 `ask` 问用户，
   绝不允许"看不清就随便选"或"看不清就跳过"。
5. 拿不准答案时按这个顺序找依据：① `{"type":"knowledge","query":"题干关键词"}` 查本地知识库（导入过课件才有料）
   → ② `{"type":"web_search","query":"题干里的关键词"}` 联网搜（最多 4 条，看摘要够判断就行；
   想细看某条再 `{"type":"web_open","url":"..."}`）→ ③ 还不行才 `ask` 让用户给答案。
   **绝不瞎猜**：`ask` 永远比猜错便宜，而且用户就在电脑前。
6. 多选题少选也算错：勾完每一个你确定的选项，提交前复查可选数量（题干写"多选"通常 2~4 个）。
7. 提交后如果结果页出现红叉 / 低分，**不要急着往下翻**：先记下哪几题错了，
   并 `{"type":"ask",...}` 说明情况，让用户决定要不要重做（很多平台不允许重考）。


## 看不清怎么办（重要）
截图分辨率有限，小图标、小字、菜单项常常糊。**先放大再看，不要猜坐标**：
- 目标区域小于屏幕的 1/4，或文字小于按钮宽度的一半 → 先 `{"type":"zoom",...}` 放大，下一帧看清了再点
- 放大视图里的网格数字仍然是**全屏 0~1000**，直接按它给坐标，不用换算
- 操作完不确定效果 → 也可以放大看细节，再 `{"type":"zoom","reset":true}` 回全屏继续
- 同一处连续点两次没反应，八成是坐标估偏了：放大确认位置，而不是换坐标硬点

## 用户指示优先（最高优先级）
- 提示词里【用户明确指示】一栏出现过的规则，**每一步都要先对照一遍**再动手
- 它有最终否决权：经验库说 win+e 好用、你的习惯想按快捷键，都**不能**覆盖用户说的
- 每轮决策前自问一句：「我这一步违反用户刚才说的哪条了吗？」

## 用户指定了操作方式时，照做，别自作聪明
- 用户说「用鼠标点任务栏图标」→ 就点图标，**不要**改用 Win+E / Win+R 等快捷键
- 用户说「用键盘」→ 就只用键盘
- 只有用户没限定、或原方式确实失败了（且有记录），才换方法
- 任务栏图标要点准：Windows 11 从左到右通常是「开始 · 搜索 · 任务视图 · 资源管理器（黄色文件夹）」，
  **不要想当然认为资源管理器是第 2 个**——先看截图数清楚，再点它的正中
- 点了任务栏后系统要 ~1 秒才弹出窗口，不要立刻判定失败

## 任务清单（可随时改写，随机应变）
- 步骤超过 3 个、或中途发现原计划走不通时，先 `{"type":"plan","steps":["...","..."]}` 写清单
- 做完一条立刻 `{"type":"step","index":1,"status":"done"}`；走不通就 `"status":"skip"`，
  想换法子就 `"status":"switch"`（会自动把下一条设为进行中）
- **同一件事试了 2~3 次都没成**：不要硬磕，skip 掉换方案，或重新 plan
- 只有「极其特殊」才问人（危险操作、要删重要数据、路径完全不知道）：
  `{"type":"ask","question":"确认要删除 xxx 吗？","options":["确认","取消"]}`
- **正常情况下不要问人，自己判断自己干**

## 用户指示优先（最高优先级）
- 提示词里【用户明确指示】一栏出现过的规则，**每一步都要先对照一遍**再动手
- 它有最终否决权：经验库说 win+e 好用、你的习惯想按快捷键，都**不能**覆盖用户说的
- 每轮决策前自问一句：「我这一步违反用户刚才说的哪条了吗？」

## 用户指定了操作方式时，照做，别自作聪明
- 用户说「用鼠标点任务栏图标」→ 就点图标，**不要**改用 Win+E / Win+R 等快捷键
- 用户说「用键盘」→ 就只用键盘
- 只有用户没限定、或原方式确实失败了（且有记录），才换方法
- 任务栏图标要点准：Windows 11 从左到右通常是「开始 · 搜索 · 任务视图 · 资源管理器（黄色文件夹）」，
  **不要想当然认为资源管理器是第 2 个**——先看截图数清楚，再点它的正中
- 点了任务栏后系统要 ~1 秒才弹出窗口，不要立刻判定失败

## 任务清单（可随时改写，随机应变）
- 步骤超过 3 个、或中途发现原计划走不通时，先 {"type":"plan","steps":["...","..."]} 写清单
- 做完一条立刻 {"type":"step","index":1,"status":"done"}；走不通就 "status":"skip"，
  想换法子就 "status":"switch"（会自动把下一条设为进行中）
- 同一件事试了 2~3 次都没成：不要硬磕，skip 掉换方案，或重新 plan
- 只有「极其特殊」才问人（危险操作、要删重要数据、路径完全不知道）：
  {"type":"ask","question":"确认要删除 xxx 吗？","options":["确认","取消"]}
- 正常情况下不要问人，自己判断自己干

## 用户指示优先（最高优先级）
- 提示词里【用户明确指示】一栏出现过的规则，**每一步都要先对照一遍**再动手
- 它有最终否决权：经验库说 win+e 好用、你的习惯想按快捷键，都**不能**覆盖用户说的
- 每轮决策前自问一句：「我这一步违反用户刚才说的哪条了吗？」

## 用户指定了操作方式时，照做，别自作聪明
- 用户说「用鼠标点任务栏图标」→ 就点图标；用户说「用键盘」→ 就只用键盘
- 只有用户没限定、或原方式确实失败过，才换方法

## 经验库只是参考，不是命令
- 经验库里写着「某快捷键有效」也不代表它适合当前任务；**与上面的硬规则冲突时，一律按硬规则**
- 特别地：经验里若出现「win+r / win+e 打开 xx」，那只能用在"确实没有该窗口"的场合，
  **不能**用来"切换"到已打开的窗口
- 经验库认定无效的做法，最多再试 1 次（有时是上次时机不对），仍不行就换

## 切换窗口优先级（发现前台不对时，按这个顺序，别跳步）
1. **alt+tab** —— 90% 的情况这一步就够，可连按 2~3 次轮换
2. **win+tab** —— 窗口多、alt+tab 轮不清时用，任务视图里点缩略图
3. 点任务栏上**已点亮**的图标
4. 都失败了才 `probe windows` 查清单
5. **永不**用 win+e / win+r / 开始菜单搜索来"切换"（那是新开）

## 切换已有窗口 vs 打开新窗口（常见错误）
- **要切到已经开着的窗口**：用 `Alt+Tab`（多按几次轮换）或 `Win+Tab`（任务视图里点缩略图），
  也可以点任务栏上**已有点亮的**图标
- **不要用 Win+E / Win+R 去"切换"**——那不是切换，是**新开一个窗口**，
  会让桌面多出重复窗口，用户看到的就是"我刚才那个窗口呢"
- 判断依据：任务栏上该程序已有亮起的图标 → 说明它已经开着 → 只用切换，不要再启动
- **切窗口首选 `{"type":"focus","title":"NEKOPARA"}`**（title 填窗口标题片段，app 填进程名片段）：
  直接按标题找窗口并激活，不用猜 alt+tab 的顺序、不用点缩略图；成功会返回「已切到…」
- 找不到标题时才退回三招：① `{"type":"hotkey","keys":["alt","tab"]}`（可连按 2~3 次轮换）
  ② `win+tab` 任务视图后点缩略图 ③ 点任务栏上已点亮的图标
- **点在非前台窗口上的第一下只是"激活窗口"**，不一定会传到控件：详情里说前台变了就直接再来一次同样的点击
- **绝不允许**用 `win+r` 敲 explorer、或 `win+e`、或从开始菜单搜索程序来"切换"——
  这些都会新开一个窗口，用户会觉得"我刚才那个窗口呢"
- 点击任务栏判"无效"时，先 `probe windows` 确认窗口到底开没开，再决定按 Alt+Tab 还是不按；
  不要一失败就上快捷键
- 任务栏图标先数清楚再点：Windows 11 从左到右常是「开始 · 搜索 · 任务视图 · 资源管理器（黄文件夹）」，
  别想当然认为资源管理器是第 2 个；点它的图标正中
- 点任务栏后系统约 1 秒才弹窗，不要立刻判失败

## 状态一致性（避免自相矛盾的操作）
- **刚打开的窗口要在里面继续做事**，别因为挡视线就关掉：先想清楚开它是为什么（开 cmd 是为了敲命令，就先敲命令）
- 关窗口前先问：这一步的目标完成了吗？没完成别关
- **上一步刚打开的窗口，下一步要在里面继续做事**，不要因为"它挡视线"就关掉——
  想清楚你打开它是为了干什么（打开 cmd 是为了敲命令，那就先敲命令）
- 关窗口前先问自己：这一步的目标完成了吗？没完成就别关

- 每次只改变界面的**一个变量**，做完先看结果再决定下一步。
- 如果上一步刚做过 X（比如按了 esc 关弹窗），不要立刻做与 X 相反的动作（比如又按 enter 确认）——
  先确认当前画面到底是什么状态。
- 同一个目标连续两次没反应，说明你对界面的判断错了：**退一步**（esc / 点空白处 / alt+tab 看别的窗口），
  不要在原地换坐标继续点。
- 弹出对话框时先读它的按钮文字再点；不确定哪个是"确定"，就用 esc 取消重来，不要乱按 enter。
- 输入前先确认光标在输入框里（截图里能看到插入光标或输入框高亮）。

## 决策规则
1. 能用快捷键就别找坐标；必须点击时先读网格刻度，点控件中心而不是边缘。
2. 一次只做一个"可见"动作；"打开运行框 → 输入 → 回车"这类可预期流程可用 sequence 合并。
3. 动作后界面没变化 = 没生效：换一种方式（优先快捷键），或先按 esc 回到稳定状态再试。
4. 不确定界面是否加载完，就 wait 1 秒再看；不要连点。
5. 目标完成、或无法继续时，输出 {"type":"done"} 并在 thought 里说明。
6. **预设步骤只是参考路线**：某一步走不通就跳过或换路线，不要为了「按步骤走」而反复尝试同一个操作。
7. 标了「已失效」的动作绝对不要再做，必须换手段：换快捷键、换入口、换坐标区间。

## 输入代码的注意事项（最容易出错的地方）
- 输入文本统一用 {"type":"type","text":"..."}：内部走剪贴板粘贴，不经过输入法，不会被变成全角。
- 代码里的标点必须是英文半角：() [] {} "" '' = : , . ; 不要用中文标点。
- 输入前先确认光标在编辑区：必要时先 click 编辑区，或 ctrl+home 回到文件开头。
- 如果发现上一步输入的文本与预期不一致（多了全角字符、缺字、被截断），不要逐字删：
  先 ctrl+a 全选，再用 type 整段重输。

## 安全红线
- 不执行删除文件、格式化、卸载、关机、注销、修改系统设置等破坏性操作。
- 不输入密码、支付信息；遇到登录/授权页直接 done 并说明。
- 不确定后果时停下来 wait，不要乱点。

## 示例
示例 A（打开记事本并写内容）：
{"thought":"用 Win+R 打开运行框，比找开始菜单更稳","action":{"type":"hotkey","keys":["win","r"]},"done":false}
下一次：{"thought":"运行框已出现，输入程序名并回车","action":{"type":"sequence","actions":[{"type":"type","text":"notepad"},{"type":"key","key":"enter"}]},"done":false}
再下一次：{"thought":"记事本已打开，先输入标题","action":{"type":"type","text":"Hello CodeMentor"},"done":false}

示例 B（切换回编辑器）：
{"thought":"需要回到 VS Code，用 Alt+Tab 切换","action":{"type":"hotkey","keys":["alt","tab"]},"done":false}"""


def parse_action_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]          # 模型偶尔把对象包成 [{...}]
            if isinstance(data, dict):
                # 模型有时直接把 action 写在顶层（没有 action 字段），这里兼容一下
                if "action" not in data and any(
                    k in data for k in ("type", "keys", "key", "text", "x")
                ):
                    note = str(data.pop("thought", ""))
                    return {"thought": note, "action": data}
                return data
        except json.JSONDecodeError:
            pass
    return {"thought": text[:200] or "模型未返回有效动作", "action": {"type": "wait", "seconds": 1}}


@dataclass
class Runner:
    session_id: str
    running: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    stopped: bool = False
    last_action: str = "（尚未执行动作）"
    recent: list[str] = field(default_factory=list)   # 最近几步的「动作 → 结果」
    signatures: list[str] = field(default_factory=list)  # 用于检测原地打转
    last_type_text: str = ""                          # 上一步输入过的文本，用于自检
    last_type_step: int = 0
    last_frame_hash: str = ""                         # 上一帧指纹（旧，保留兼容）
    last_sig: bytes = b""                             # 64×40 灰度指纹
    checklist: list[dict[str, str]] = field(default_factory=list)   # 可随机应变的任务清单
    last_action_desc: str = ""                            # 最近执行的动作描述，用于「目标达成」记经验
    edit_variant: str = "home_end"                     # 当前编辑器适用的整行选中手法
    neutral_streak: int = 0                           # 连续「看不出变化但不算失败」的次数
    # ---- 经验学习 ----
    failed: dict[str, str] = field(default_factory=dict)  # 动作指纹 → 可读描述（本会话禁用）
    pending: dict | None = None                       # 上一步动作，等下一帧来判定成败
    fail_streak: int = 0                              # 连续无效次数
    blocked_streak: int = 0                           # 连续给出已失效动作的次数
    app_scope: str = GLOBAL_SCOPE
    lessons_text: str = ""
    last_action_at: float = 0.0                       # 上一次真正操作的时间
    model_errors: int = 0                             # 视觉模型连续失败次数
    retry_attempts: int = 0                           # 当前动作原地重试了几次
    force_switch: bool = False                        # 是否要求模型必须换方案
    zoom: dict | None = None                          # 当前放大观察的区域（全屏 0~1000）
    last_click: tuple[float, float] | None = None     # 上次点击的归一化坐标（放大时画准星）
    controls_text: str = ""                          # 最近一次控件树（注入提示词）
    controls_window: str = ""                        # 控件树所属窗口
    answers: list[dict[str, str]] = field(default_factory=list)   # 学习者对提问的回答
    asked: list[str] = field(default_factory=list)                # already 问过的问题（防重复提问）
    force_act: bool = False                                       # 禁止再问，必须执行动作
    frame_context: list[str] = field(default_factory=list)   # 本帧内的取证结果（换帧才清空）
    probe_count: int = 0                              # 本帧已取证次数
    deciding: bool = False                            # 是否正在思考（防止重入）
    last_decision_at: float = 0.0                     # 上次决策结束时间
    skip_streak: int = 0                              # 连续跳过模型调用的次数
    same_frame_streak: int = 0                        # 连续「画面与上一帧完全一样」的次数
    click_history: list[dict[str, Any]] = field(default_factory=list)  # 最近点过哪里（防重复勾选）
    console_tucked: bool = False                      # 是否已经替用户最小化过控制台
    last_cheap_action: bool = False                   # 上一步是 wait/key/scroll 这类便宜动作
    recent_fps: list[str] = field(default_factory=list)                # 最近动作指纹（防死循环）
    last_think_at: float = 0.0                        # 上次调用模型的时间
    last_shot_at: float = 0.0                         # 上次抓帧的时间


class ScreenController:
    """单例，管理所有屏幕演示会话。"""

    def __init__(self) -> None:
        self.capture = ScreenCapture(monitor=settings.screen_monitor)
        self._runners: dict[str, Runner] = {}
        # 学习者的回答 / 已提过的问题要跨「runner 重启」保留：
        # 模型 ask 之后循环是 return 结束的，回答时 resume 会新建一个 Runner，
        # 只存在 Runner.answers 里的话，回答会被静默丢掉 —— 表现就是「答了它又问一遍」。
        self._answers: dict[str, list[dict[str, str]]] = {}
        self._asked: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ 持久化
    async def create_session(
        self,
        *,
        user_id: int,
        conversation_id: str | None,
        goal: str,
        steps: list[str],
        interval_ms: int | None = None,
        max_steps: int | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        async with session_scope() as session:
            row = ScreenSession(
                user_id=user_id,
                conversation_id=conversation_id,
                goal=goal or "跟着助手完成一次编程练习",
                plan=steps or [],
                interval_ms=int(interval_ms or settings.screen_interval_ms),
                max_steps=int(max_steps or settings.screen_max_steps),
                dry_run=bool(settings.screen_dry_run if dry_run is None else dry_run),
                status="idle",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            payload = self._serialize(row)

        # 从对话里学习：用户说过的操作指示（"用 Ctrl+Shift+P 打开命令面板"）记成经验
        try:
            await self._learn_from_conversation(conversation_id, goal)
        except Exception as exc:  # noqa: BLE001
            logger.debug("从对话学习失败: %s", exc)
        await bus.publish(f"screen:{row.id}", {"type": "created", "session": payload})
        return payload

    async def _learn_from_conversation(self, conversation_id: str | None, goal: str) -> None:
        """把用户最近说过的操作指示记进经验库。"""
        texts: list[str] = [goal or ""]
        if conversation_id:
            from app.db.models import Message

            async with session_scope() as session:
                rows = (
                    (
                        await session.execute(
                            select(Message.content)
                            .where(Message.conversation_id == conversation_id, Message.role == "user")
                            .order_by(desc(Message.id))
                            .limit(8)
                        )
                    )
                    .scalars()
                    .all()
                )
            texts.extend(str(t or "") for t in rows)
        learned = 0
        for text in texts:
            learned += await learn_from_text(text)
        if learned:
            logger.info("从对话中学到 %s 条操作经验", learned)

    async def get(self, session_id: str) -> dict[str, Any]:
        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is None:
                raise NotFoundError("屏幕演示会话不存在")
            steps = (
                await session.execute(
                    select(ScreenStep)
                    .where(ScreenStep.session_id == session_id)
                    .order_by(desc(ScreenStep.id))
                    .limit(60)
                )
            ).scalars().all()
            payload = self._serialize(row)
            payload["steps_log"] = [self._serialize_step(s) for s in reversed(steps)]
            return payload

    async def list_sessions(self, user_id: int = 1, limit: int = 20) -> list[dict[str, Any]]:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(ScreenSession)
                    .where(ScreenSession.user_id == user_id)
                    .order_by(desc(ScreenSession.created_at))
                    .limit(limit)
                )
            ).scalars().all()
            return [self._serialize(r) for r in rows]

    # ------------------------------------------------------------------ 控制
    async def start(self, session_id: str) -> dict[str, Any]:
        runner = self._runners.get(session_id)
        if runner and runner.task and not runner.task.done():
            runner.running.set()
            await self._set_status(session_id, "running")
            return await self.get(session_id)

        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is None:
                raise NotFoundError("屏幕演示会话不存在")
            if row.status == "completed":
                raise ScreenControlError("该演示已经完成，请重新生成一个演示")
            row.status = "running"
            row.started_at = row.started_at or utcnow()
            row.last_error = None
            await session.commit()

        IME_GUARD.enabled = bool(settings.screen_ime_guard)
        runner = Runner(session_id=session_id)
        # 接着上次的回答继续：模型提问会结束循环，回答后是新 Runner，不接上就白答了
        runner.answers = list(self._answers.get(session_id, []))
        runner.asked = list(self._asked.get(session_id, []))
        runner.running.set()
        self._runners[session_id] = runner
        runner.task = asyncio.create_task(self._loop(session_id), name=f"screen-{session_id}")

        if settings.screen_ime_guard:
            switched = IME_GUARD.ensure_ascii()
            await bus.publish(
                f"screen:{session_id}",
                {
                    "type": "notice",
                    "level": "info" if switched else "warning",
                    "message": (
                        "输入保护：已把前台程序临时切到英文输入法"
                        if switched
                        else "输入保护：当前程序不支持自动切输入法（新式程序走 TSF），"
                        "但文本输入走剪贴板粘贴并自动纠正全角标点，不受输入法影响"
                    ),
                },
            )

        await bus.publish(
            f"screen:{session_id}",
            {"type": "status", "status": "running", "message": "屏幕演示已启动"},
        )
        return await self.get(session_id)

    async def pause(self, session_id: str) -> dict[str, Any]:
        runner = self._runners.get(session_id)
        if runner is None:
            await self._set_status(session_id, "paused")
            return await self.get(session_id)
        runner.running.clear()
        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is not None:
                if row.status == "running":
                    row.status = "paused"
                    row.updated_at = utcnow()
                    await session.commit()
                step = row.current_step
        await bus.publish(
            f"screen:{session_id}",
            {
                "type": "status",
                "status": "paused",
                "message": f"已在第 {step} 步暂停，恢复时会从这里继续",
                "current_step": step,
            },
        )
        return await self.get(session_id)

    async def resume(self, session_id: str) -> dict[str, Any]:
        runner = self._runners.get(session_id)
        if runner is None or runner.task is None or runner.task.done():
            return await self.start(session_id)
        runner.running.set()
        await self._set_status(session_id, "running")
        await bus.publish(
            f"screen:{session_id}",
            {"type": "status", "status": "running", "message": "已从暂停点继续"},
        )
        return await self.get(session_id)

    async def stop(self, session_id: str) -> dict[str, Any]:
        IME_GUARD.restore_all()
        self._answers.pop(session_id, None)
        self._asked.pop(session_id, None)
        runner = self._runners.get(session_id)
        if runner is not None:
            runner.stopped = True
            runner.running.set()
            if runner.task and not runner.task.done():
                runner.task.cancel()
            self._runners.pop(session_id, None)
        await self._set_status(session_id, "completed")
        await bus.publish(
            f"screen:{session_id}", {"type": "status", "status": "completed", "message": "演示已结束"}
        )
        return await self.get(session_id)

    async def update_interval(self, session_id: str, interval_ms: int) -> dict[str, Any]:
        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is None:
                raise NotFoundError("屏幕演示会话不存在")
            row.interval_ms = max(800, min(int(interval_ms), 30000))
            row.updated_at = utcnow()
            await session.commit()
        return await self.get(session_id)

    async def recover_stale(self) -> None:
        """服务重启后，把中断的会话标记为暂停，保留步骤以便续跑。"""
        try:
            async with session_scope() as session:
                rows = (
                    await session.execute(
                        select(ScreenSession).where(ScreenSession.status == "running")
                    )
                ).scalars().all()
                for row in rows:
                    row.status = "paused"
                    row.last_error = "服务重启导致中断，可从当前步骤继续"
                await session.commit()
            if rows:
                logger.info("已恢复 %s 个中断的屏幕演示会话（标记为 paused）", len(rows))
        except Exception as exc:  # noqa: BLE001
            logger.warning("恢复中断会话失败: %s", exc)

    async def shutdown(self) -> None:
        IME_GUARD.restore_all()
        for runner in list(self._runners.values()):
            runner.stopped = True
            if runner.task and not runner.task.done():
                runner.task.cancel()
        self._runners.clear()

    # ------------------------------------------------------------------ 主循环
    async def _loop(self, session_id: str) -> None:
        runner = self._runners[session_id]
        channel = f"screen:{session_id}"
        try:
            while not runner.stopped:
                if not runner.running.is_set():
                    await asyncio.sleep(0.3)
                    continue

                # 上一步刚操作完就立刻截图，可能拍到还没刷新完的界面
                if runner.last_action_at:
                    settle = 0.6 - (time.perf_counter() - runner.last_action_at)
                    if settle > 0:
                        await asyncio.sleep(settle)

                loop_started = time.perf_counter()

                async with session_scope() as session:
                    row = await session.get(ScreenSession, session_id)
                    if row is None:
                        return
                    if row.status == "completed":
                        return
                    state = {
                        "goal": row.goal,
                        "plan": list(row.plan or []),
                        "current_step": row.current_step,
                        "max_steps": row.max_steps,
                        "interval_ms": row.interval_ms,
                        "dry_run": row.dry_run,
                        "user_id": row.user_id,
                    }

                if state["current_step"] >= state["max_steps"]:
                    await self._finish(session_id, "已达到最大步数，演示结束")
                    return

                await bus.publish(
                    channel,
                    {
                        "type": "observing",
                        "step": state["current_step"] + 1,
                        "message": "正在截屏并识别界面…",
                    },
                )

                # 1) 截屏（存原图给界面看，送模型的是带坐标网格的版本）
                capture_gap = max(0.15, float(getattr(settings, "screen_capture_ms", 500)) / 1000.0)
                since_shot = time.perf_counter() - (runner.last_shot_at or 0.0)
                if runner.last_shot_at and since_shot < capture_gap:
                    await asyncio.sleep(capture_gap - since_shot)
                try:
                    shot = await self.capture.grab(runner.zoom)
                    path = self.capture.save(shot["image"], session_id)
                    data_url = self.capture.to_data_url(self.capture.draw_grid(shot["image"]))
                    screen_size = shot["screen_size"]
                    shot_url = f"/static/screenshots/{session_id}/{path.name}"
                    sig = self.capture.signature(shot["image"])
                    ratio = self.capture.diff_ratio(sig, runner.last_sig) if runner.last_sig else 1.0
                    # 选区高亮/按钮态变化通常在 1% 以上；光标闪烁 <0.5%，忽略
                    same_frame = bool(runner.last_sig) and ratio < 0.005
                    runner.same_frame_streak = runner.same_frame_streak + 1 if same_frame else 0
                    runner.last_sig = sig or runner.last_sig
                    runner.last_shot_at = time.perf_counter()
                    runner.frame_context = []          # 新的一帧：清空上一帧的取证记录
                except Exception as exc:  # noqa: BLE001
                    await self._fail(session_id, f"截图失败：{exc}")
                    return

                await bus.publish(
                    channel,
                    {"type": "screenshot", "url": shot_url, "step": state["current_step"] + 1},
                )

                # 1.5) 用这一帧给上一步动作"判卷"：界面变了=有效，没变=无效并记入经验库
                verdict = await self._judge_previous(
                    runner, state, channel, session_id, same_frame, screen_size
                )
                if not runner.running.is_set():
                    continue
                if verdict == "retried":
                    continue

                # 1.8) 画面没变、也没有待判定动作 → 不必打扰模型（省钱也省时间）
                #      连续跳过 8 次（约 4 秒）仍无变化就强制问一次，避免哈希漏检导致干等
                skip_enabled = bool(getattr(settings, "screen_skip_unchanged", True))
                if (
                    skip_enabled
                    and same_frame
                    and runner.pending is None
                    and state["current_step"] > 0
                    and runner.skip_streak < 8
                ):
                    runner.skip_streak += 1
                    await asyncio.sleep(max(0.2, getattr(settings, "screen_capture_ms", 500) / 1000.0))
                    continue
                runner.skip_streak = 0

                # 1.9) 决策节流：两次问模型之间至少隔 interval_ms
                #      wait / 按键 / 滚动这类动作不需要等画面"沉淀"，只留很短缓冲
                think_gap = float(state["interval_ms"]) / 1000.0
                if runner.last_cheap_action:
                    think_gap = min(think_gap, 0.45)
                since_last = time.perf_counter() - (runner.last_think_at or 0.0)
                if runner.last_think_at and since_last < think_gap:
                    await asyncio.sleep(think_gap - since_last)
                runner.last_think_at = time.perf_counter()

                # 2) 思考循环：同一张图里可反复取证，直到摸清情况再动手
                decision: dict[str, Any] = {}
                runner.probe_count = 0
                try:
                    while True:
                        runner.deciding = True
                        try:
                            decision = await self._decide(state, data_url, runner, same_frame)
                        finally:
                            runner.deciding = False
                            runner.last_decision_at = time.perf_counter()

                        probe = decision.get("probe")
                        if not isinstance(probe, dict) or not probe.get("tool"):
                            break

                        runner.probe_count += 1
                        if runner.probe_count > 3:
                            runner.frame_context.append(
                                "【系统】取证次数已达上限，必须基于现有信息给出一个动作。"
                            )
                            break

                        observation = await self._run_probe(probe)
                        runner.frame_context.append(
                            f"【取证#{runner.probe_count}·{probe.get('tool')}】{observation}"
                        )
                        await bus.publish(
                            channel,
                            {
                                "type": "notice",
                                "level": "info",
                                "message": f"取证：{probe.get('tool')} → {observation[:60]}",
                            },
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("视觉模型调用失败: %s", exc)
                    runner.model_errors += 1
                    await bus.publish(
                        channel,
                        {
                            "type": "notice",
                            "level": "warning",
                            "message": f"视觉模型调用失败（第 {runner.model_errors} 次）：{exc}",
                        },
                    )
                    # 按约定：只有模型出错才强制中断
                    await self._fail(session_id, f"视觉模型调用失败，演示已中断：{exc}")
                    return

                thought = str(decision.get("thought") or "")
                raw_action = decision.get("action") or {"type": "wait"}

                # 先规范化：模型偶尔会给出不合法动作，转成可读提示而不是崩溃
                try:
                    action = normalize_action(raw_action)
                except ActionError as exc:
                    action = {"type": "wait", "seconds": 1.0}
                    thought = f"{thought}（动作不合法：{exc}，改为等待）".strip()

                # edit_line：套用这个编辑器学到的整行选中手法
                if action.get("type") == "edit_line" and action.get("variant", "auto") == "auto":
                    try:
                        from app.screen_agent import editor_profiles

                        action["variant"] = editor_profiles.best_variant(runner.app_scope)
                    except Exception:  # noqa: BLE001
                        action["variant"] = "home_end"

                runner.last_action_desc = desc
                uia_done, swapped, uia_note = await self._handle_uia(action, runner)
                if uia_done:
                    await bus.publish(
                        channel, {"type": "notice", "level": "info", "message": uia_note}
                    )
                    await self._save_step(session_id, state, runner, uia_note, action, shot_url, "info")
                    continue
                if swapped is not None:
                    await bus.publish(
                        channel, {"type": "notice", "level": "info", "message": uia_note}
                    )
                    action = swapped

                if action["type"] == "ask":
                    paused = await self._ask_user(session_id, state, runner, action, thought, shot_url)
                    if paused:
                        return
                    # 重复提问被忽略：带着「不许再问」的指令继续下一步
                    await bus.publish(
                        channel,
                        {"type": "notice", "level": "warning", "message": "按之前的回答继续，不再重复提问"},
                    )
                    continue

                if action["type"] == "plan":
                    runner.checklist = [
                        {"title": s, "status": "doing" if i == 0 else "todo"}
                        for i, s in enumerate(action["steps"])
                    ]
                    await bus.publish(
                        channel,
                        {"type": "notice", "level": "info",
                         "message": "任务清单：\n" + "\n".join(
                             f"{i+1}. {x['title']}" for i, x in enumerate(runner.checklist))},
                    )
                    await self._save_step(session_id, state, runner, "重写任务清单", action, shot_url, "info")
                    continue

                if action["type"] == "step":
                    idx, st = int(action["index"]), action["status"]
                    for i, item in enumerate(runner.checklist):
                        if i + 1 == idx:
                            item["status"] = st
                            if st in ("done", "switch"):
                                for j, other in enumerate(runner.checklist):
                                    if j > i and other["status"] == "todo":
                                        other["status"] = "doing"
                                        break
                    # 只有「模型确认这一子目标完成」才记成功经验——
                    # 画面变化不等于目标达成（Win+E 也会让画面变）
                    if st == "done" and runner.last_action_desc:
                        try:
                            await record_lesson(
                                scope=runner.app_scope or GLOBAL_SCOPE,
                                action={"type": "goal"},
                                outcome="success",
                                method=runner.last_action_desc,
                                goal=str(action.get("note") or "子目标完成"),
                                note="目标达成",
                            )
                        except Exception:  # noqa: BLE001
                            pass
                    await bus.publish(
                        channel,
                        {"type": "notice", "level": "info",
                         "message": f"任务 #{idx} → {st} {action.get('note','')}"},
                    )
                    await self._save_step(session_id, state, runner, f"任务 #{idx} {st}", action, shot_url, "info")
                    continue

                if action["type"] == "probe":
                    observation = await self._run_probe(action)
                    runner.frame_context.append(
                        f"【取证·{action.get('tool')}】{observation}"
                    )
                    await bus.publish(
                        channel,
                        {"type": "notice", "level": "info", "message": f"取证：{observation[:70]}"},
                    )
                    await self._save_step(
                        session_id, state, runner, thought or "取证", action, shot_url, "info"
                    )
                    continue

                if action["type"] == "knowledge":
                    # 答题前先查本地知识库：结果回到下一帧的提示词里，不用额外截图
                    query = str(action.get("query") or "")
                    observation = await self._run_knowledge(query)
                    runner.frame_context.append(f"【查知识库·{query[:24]}】{observation}")
                    await bus.publish(
                        channel,
                        {"type": "notice", "level": "info",
                         "message": f"查知识库：{observation[:70]}"},
                    )
                    await self._save_step(
                        session_id, state, runner, thought or "查知识库", action, shot_url, "info"
                    )
                    continue

                if action["type"] in ("web_search", "web_open"):
                    # 知识库没有的东西（课程外名词、常识）才联网，结果同样回到提示词里
                    observation = await self._run_web(action)
                    label = action.get("query") or action.get("url") or ""
                    runner.frame_context.append(f"【联网·{str(label)[:24]}】{observation}")
                    await bus.publish(
                        channel,
                        {"type": "notice", "level": "info",
                         "message": f"联网：{observation[:70]}"},
                    )
                    await self._save_step(
                        session_id, state, runner, thought or "联网搜索", action, shot_url, "info"
                    )
                    continue
                if action["type"] == "zoom":
                    region = action.get("region") or {}
                    if (
                        region.get("x0", 0) <= 0
                        and region.get("y0", 0) <= 0
                        and region.get("x1", 1000) >= 1000
                        and region.get("y1", 1000) >= 1000
                    ):
                        runner.zoom = None
                        msg = "已切回全屏视角"
                    else:
                        runner.zoom = region
                        msg = (
                            f"已放大观察 x{region.get('x0',0):.0f}-{region.get('x1',1000):.0f}"
                            f" / y{region.get('y0',0):.0f}-{region.get('y1',1000):.0f}，"
                            "坐标仍按全屏 0~1000 给"
                        )
                    await bus.publish(
                        channel, {"type": "notice", "level": "info", "message": msg}
                    )
                    continue

                if bool(decision.get("done")) or action["type"] == "done":
                    await self._retrospect(state, runner)
                    await self._finish(session_id, thought or "目标已完成")
                    return

                # 防呆：已失效的动作不再执行；同一动作重复出现也直接判失效（少走弯路）
                signature = json.dumps(action, ensure_ascii=False, sort_keys=True)
                key = action_key(action)
                block_reason = ""
                if action["type"] not in NO_VERDICT_KINDS:
                    if key in runner.failed:
                        block_reason = f"「{runner.failed[key]}」此前已失败"
                    elif signature in runner.signatures:
                        block_reason = f"「{describe_action(action)}」刚才做过但没有效果"
                        runner.failed[key] = describe_action(action)
                        await record_lesson(
                            scope=runner.app_scope,
                            action=action,
                            outcome="failure",
                            method=describe_action(action),
                            goal=state["goal"],
                            note="重复执行无变化",
                        )
                if block_reason:
                    runner.blocked_streak += 1
                    await bus.publish(
                        channel,
                        {
                            "type": "notice",
                            "level": "warning",
                            "message": f"{block_reason}，已跳过这一步，请换一种方法",
                        },
                    )
                    # 不再暂停：把这次也算作一步，靠 max_steps 兜底，同时逼模型换方法
                    runner.force_switch = True
                    step_idx = state["current_step"] + 1
                    async with session_scope() as session:
                        session.add(
                            ScreenStep(
                                session_id=session_id,
                                idx=step_idx,
                                thought=block_reason,
                                action=action,
                                status="skipped",
                                screenshot=shot_url,
                            )
                        )
                        row2 = await session.get(ScreenSession, session_id)
                        if row2 is not None:
                            row2.current_step = step_idx
                        await session.commit()
                    await asyncio.sleep(0.8)
                    continue
                runner.blocked_streak = 0

                # 3) 记录步骤（先落库，暂停/中断后可续）
                step_idx = state["current_step"] + 1
                async with session_scope() as session:
                    step = ScreenStep(
                        session_id=session_id,
                        idx=step_idx,
                        thought=thought,
                        action=action,
                        status="pending",
                        screenshot=shot_url,
                    )
                    session.add(step)
                    row = await session.get(ScreenSession, session_id)
                    if row is not None:
                        row.current_step = step_idx
                    await session.commit()
                    await session.refresh(step)

                # 3.85) focus 不带标题：默认切回本轮的演示目标，省得模型猜
                if action.get("type") == "focus" and not action.get("query"):
                    action["query"] = runner.app_scope or ""
                    if action["query"]:
                        runner.frame_context.append(
                            f"（系统：focus 没写标题，按演示目标 {action['query']} 处理）"
                        )

                # 3.9) 前台是自家控制台就先让开：点它等于白点，画面也不会动
                if action.get("type") not in ("wait", "done", "plan", "step", "probe", "knowledge",
                                             "web_search", "web_open", "ask", "focus", "zoom"):
                    room_note = await self._make_room(runner)
                    if room_note:
                        runner.frame_context.append(room_note)
                        await bus.publish(
                            channel,
                            {"type": "notice", "level": "info", "message": room_note[:70]},
                        )

                # 4) 执行动作
                if action.get("type") in ("click", "double_click", "right_click"):
                    try:
                        runner.last_click = (float(action.get("x", 0)), float(action.get("y", 0)))
                    except (TypeError, ValueError):
                        pass
                    # 记录点位：勾选框/单选钮点第二次会**取消选中**，所以同一位置反复点必须提醒
                    repeat_note = self._note_repeat_click(runner, action, step_idx)
                    loop_note = self._loop_hint(runner, action)
                    if loop_note:
                        runner.frame_context.append(loop_note)
                else:
                    repeat_note = ""
                ok, detail = await self._execute_action(action, screen_size, state["dry_run"])
                if repeat_note:
                    detail = f"{detail}{repeat_note}"
                if state["dry_run"]:
                    await asyncio.sleep(0.4)

                runner.last_action = f"第{step_idx}步 {action['type']} → {detail}"
                if action["type"] == "type":
                    runner.last_type_text = action.get("text", "")
                    runner.last_type_step = step_idx
                # 交给下一帧判定成败（type/wait 这种不改变界面的动作不判）
                runner.last_action_at = time.perf_counter()
                if action["type"] not in NO_VERDICT_KINDS:
                    runner.pending = {
                        "action": action,
                        "key": key,
                        "scope": runner.app_scope,
                        "step": step_idx,
                    }
                runner.last_cheap_action = action["type"] in (
                    "wait", "key", "hotkey", "scroll", "page", "type",
                )
                runner.signatures.append(signature)
                runner.signatures = runner.signatures[-6:]
                runner.recent.append(f"第{step_idx}步：{describe_action(action)} → {detail}")
                runner.recent = runner.recent[-6:]
                async with session_scope() as session:
                    step_row = await session.get(ScreenStep, step.id)
                    if step_row is not None:
                        step_row.status = "done" if ok else "failed"
                        step_row.detail = detail
                        await session.commit()

                await bus.publish(
                    channel,
                    {
                        "type": "step",
                        "step": step_idx,
                        "thought": thought,
                        "action": action,
                        "detail": detail,
                        "ok": ok,
                        "screenshot": shot_url,
                    },
                )

                # 5) 间隔等待：按「本次决策总耗时」折算，避免模型慢时再白等一个完整间隔
                interval = max(0.8, state["interval_ms"] / 1000.0)
                elapsed = time.perf_counter() - loop_started
                remaining = max(0.25, interval - elapsed)
                slept = 0.0
                while slept < remaining and runner.running.is_set() and not runner.stopped:
                    await asyncio.sleep(0.2)
                    slept += 0.2

            await bus.publish(
                channel, {"type": "status", "status": "paused", "message": "循环已停止"}
            )
        except asyncio.CancelledError:  # pragma: no cover
            await bus.publish(channel, {"type": "status", "status": "paused", "message": "已取消"})
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("屏幕演示循环异常")
            await self._fail(session_id, f"演示异常中止：{exc}")
        finally:
            self._runners.pop(session_id, None)

    # ------------------------------------------------------------------ 全局停止
    async def stop_all(self, reason: str = "手动停止") -> int:
        """停掉所有正在跑的演示（强制停止快捷键走这里）。"""
        count = 0
        for session_id, runner in list(self._runners.items()):
            runner.stopped = True
            runner.running.clear()
            if runner.task and not runner.task.done():
                runner.task.cancel()
            await self._set_status(session_id, "paused")
            await bus.publish(
                f"screen:{session_id}",
                {
                    "type": "notice",
                    "level": "error",
                    "message": f"已强制停止：{reason}（进度已保存，可以点继续）",
                },
            )
            count += 1
        if count == 0:
            for session_id in await self._running_session_ids():
                await self._set_status(session_id, "paused")
                count += 1
        IME_GUARD.restore_all()
        logger.warning("强制停止：%s 个演示被中止（%s）", count, reason)
        return count

    async def _running_session_ids(self) -> list[str]:
        try:
            async with session_scope() as session:
                rows = (
                    (
                        await session.execute(
                            select(ScreenSession).where(ScreenSession.status == "running")
                        )
                    )
                    .scalars()
                    .all()
                )
            return [r.id for r in rows]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ 复盘
    async def _retrospect(self, state: dict[str, Any], runner: "Runner") -> None:
        """演示结束后让模型自己复盘，把可复用经验写回屏幕侧提示知识。

        这是「自主学习」的闭环：执行 → 观察成败（经验库）→ 总结成规则（提示知识）→ 下次生效。
        """
        if not getattr(settings, "screen_retro", True):
            return
        if len(runner.recent) < 3:
            return
        try:
            from app.llm.service import build_chat_model, resolve_model
            from app.rag.guides import upsert_guide

            async with session_scope() as session:
                resolved = await resolve_model(session, need_vision=False)
            llm = build_chat_model(
                resolved, streaming=False, temperature=0.2, max_tokens=400, thinking=False
            )
            history = "\n".join(runner.recent[-8:])
            failed = "、".join(list(runner.failed.values())[:5]) or "（无）"
            prompt = (
                "下面是一次 Windows 屏幕操作演示的过程记录。请你复盘，提炼可复用的操作经验。\n\n"
                f"目标：{state.get('goal', '')}\n"
                f"过程：\n{history}\n"
                f"被判为无效的动作：{failed}\n\n"
                "要求：输出 1-3 条经验，每条一行，动词开头，不超过 40 字，必须是可执行的具体做法"
                "（例如「在资源管理器里先 ctrl+l 输入路径，比逐层点更快」）。"
                "只输出 JSON 字符串数组，例如 [\"经验一\", \"经验二\"]，不要解释。"
            )
            resp = await llm.ainvoke(prompt)
            text = resp.content if isinstance(resp.content, str) else str(resp.content or "")
            lessons: list[str] = []
            start, end = text.find("["), text.rfind("]")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    if isinstance(parsed, list):
                        lessons = [str(x).strip() for x in parsed if str(x).strip()]
                except json.JSONDecodeError:
                    lessons = []
            if not lessons:
                lessons = [ln.strip("-· 0123456789.") for ln in text.splitlines() if len(ln.strip()) > 6]

            learned = 0
            for item in lessons[:3]:
                item = item.strip()
                if not item or len(item) > 80:
                    continue
                if await upsert_guide(title=item[:40], content=f"- {item}", target="screen"):
                    learned += 1
            if learned:
                await bus.publish(
                    f"screen:{runner.session_id}",
                    {
                        "type": "notice",
                        "level": "success",
                        "message": f"复盘完成：已把 {learned} 条经验写进屏幕侧提示知识，下次演示会自动用上",
                    },
                )
                logger.info("演示复盘产出 %s 条经验", learned)
        except Exception as exc:  # noqa: BLE001
            logger.debug("复盘失败（不影响主流程）: %s", exc)

    # ------------------------------------------------------------------ 经验判定
    RETRY_DELAYS = (1.5, 3.0)   # 多数"没变化"是点空了而非加载慢，别为它干等 15 秒

    async def _save_step(
        self,
        session_id: str,
        state: dict[str, Any],
        runner: "Runner",
        thought: str,
        action: dict[str, Any],
        shot_url: str,
        status: str = "info",
    ) -> None:
        """记一步（不执行动作的辅助类动作：读控件树、切视角等）。"""
        step_idx = state["current_step"] + 1
        state["current_step"] = step_idx
        try:
            async with session_scope() as session:
                session.add(
                    ScreenStep(
                        session_id=session_id,
                        idx=step_idx,
                        thought=thought,
                        action=action,
                        status=status,
                        screenshot=shot_url,
                    )
                )
                row = await session.get(ScreenSession, session_id)
                if row is not None:
                    row.current_step = step_idx
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("记录步骤失败: %s", exc)
        runner.recent.append(f"#{step_idx} {thought}")

    async def _ask_user(
        self,
        session_id: str,
        state: dict[str, Any],
        runner: "Runner",
        action: dict[str, Any],
        thought: str,
        shot_url: str,
    ) -> bool:
        """模型需要额外信息时暂停，等学习者填写后再继续。

        返回 True = 真的停下来等回答了（调用方应 return）；
        返回 False = 这次提问被忽略（同一个问题已经问过且答过），调用方应 continue。
        """
        question = str(action["question"] or "").strip()
        normalized = question.replace(" ", "")[:120]

        # 同一个问题已经问过、而且答过了 → 不再反复打断学习者，
        # 直接把「不许再问」的指令塞进上下文让它动手。
        already = bool(normalized) and normalized in runner.asked
        if already and runner.answers:
            runner.force_act = True
            await bus.publish(
                f"screen:{session_id}",
                {
                    "type": "notice",
                    "level": "warning",
                    "message": "模型又想问同一个问题，已按之前的回答让它直接继续",
                },
            )
            logger.info("忽略重复提问：%s", question[:40])
            return False
        if normalized:
            runner.asked.append(normalized)
            self._asked.setdefault(session_id, []).append(normalized)

        payload = {"question": question, "options": action.get("options") or []}
        runner.running.clear()
        await self._save_step(
            session_id, state, runner, thought or action["question"], action, shot_url, "waiting"
        )
        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is not None:
                row.status = "waiting"
                row.pending_question = payload
                await session.commit()
        await self._set_status(session_id, "waiting")
        await bus.publish(
            f"screen:{session_id}",
            {
                "type": "ask",
                "question": payload["question"],
                "options": payload["options"],
                "message": "模型需要你补充信息，填写后会继续演示",
            },
        )
        # 弹一个置顶小窗：演示时整屏都被别的程序占着，网页里的输入框经常看不到
        self._spawn_ask_dialog(session_id, question, payload["options"])
        logger.info("演示暂停等待输入：%s", payload["question"][:40])
        return True

    def _spawn_ask_dialog(self, session_id: str, question: str, options: list[str]) -> None:
        """起一个 tkinter 置顶窗口等回答；失败就只靠网页里的输入框。"""
        if not bool(getattr(settings, "screen_ask_dialog", True)):
            return
        try:
            import subprocess
            import sys

            argv = [
                sys.executable,
                "-m",
                "app.screen_agent.ask_dialog",
                "--base",
                f"http://127.0.0.1:{settings.port}",
                "--session",
                session_id,
                "--question",
                question,
            ]
            for opt in options[:4]:
                argv.extend(["--options", str(opt)])
            creation = 0x08000000  # CREATE_NO_WINDOW：不要多弹一个黑框
            subprocess.Popen(
                argv,
                cwd=str(Path(__file__).resolve().parents[2]),
                creationflags=creation,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("置顶提问窗启动失败（不影响演示）: %s", exc)

    async def answer(self, session_id: str, answer: str) -> dict[str, Any]:
        """接收学习者对 ask 的回答，写进上下文并继续。"""
        text = (answer or "").strip()
        if not text:
            raise ValueError("回答不能为空")
        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is None:
                raise ValueError("会话不存在")
            question = (row.pending_question or {}).get("question", "")
            row.pending_question = None
            await session.commit()

        entry = {"question": question, "answer": text}
        # 双重落点：内存里的 _answers 供「重启 runner」时接上，runner.answers 供当前轮直接用
        self._answers.setdefault(session_id, []).append(entry)
        runner = self._runners.get(session_id)
        if runner is not None:
            runner.answers.append(entry)
            runner.controls_text = ""
            runner.force_act = False
        await self._set_status(session_id, "paused")
        await bus.publish(
            f"screen:{session_id}",
            {"type": "notice", "level": "success", "message": f"已收到回答：{text[:40]}"},
        )
        await self.resume(session_id)
        return {"ok": True, "session_id": session_id, "answer": text}

    # 同一位置重复点击的判定半径（0~1000 坐标里的 ±25，约等于一个选项框的宽度）
    REPEAT_CLICK_RADIUS = 25.0

    def _note_repeat_click(self, runner: "Runner", action: dict[str, Any], step_idx: int) -> str:
        """记录点击点位；同一位置 3 步内点过就提醒「再点会取消选中」。

        单选/多选的勾选框是 toggle：点一次选中，再点一次取消。
        模型看不清勾选状态时会反复点同一个框，看起来就是「选了又自己没了」。
        """
        if action.get("x") is None or action.get("y") is None:
            return ""  # 没给坐标（比如按控件名点）就不参与重复判定
        try:
            x = float(action["x"])
            y = float(action["y"])
        except (TypeError, ValueError, KeyError):
            return ""

        radius = self.REPEAT_CLICK_RADIUS
        hit = None
        for item in runner.click_history[-6:]:
            if abs(item["x"] - x) <= radius and abs(item["y"] - y) <= radius:
                hit = item
                break

        runner.click_history.append({"x": x, "y": y, "step": step_idx})
        runner.click_history = runner.click_history[-12:]

        if hit is None:
            return ""
        gap = step_idx - int(hit["step"])
        if gap <= 0 or gap > 3:
            return ""
        return (
            f"；⚠️ 这个位置第 {hit['step']} 步刚点过（{gap} 步前）。"
            "如果是选项框，再点一次就是**取消选中**——先确认它现在是勾上还是没勾"
        )

    def _loop_hint(self, runner: "Runner", action: dict[str, Any]) -> str:
        """同一块区域反复操作时给一句强提醒（防死循环）。"""
        try:
            fp = (
                f"{action['type']}:"
                f"{round(float(action.get('x', 0)) / 25)}:"
                f"{round(float(action.get('y', 0)) / 25)}"
            )
        except (TypeError, ValueError, KeyError):
            return ""
        runner.recent_fps.append(fp)
        runner.recent_fps = runner.recent_fps[-12:]
        same = sum(1 for f in runner.recent_fps if f == fp)
        if same < 3:
            return ""
        return (
            f"【疑似死循环】你已经在同一块区域做了 {same} 次类似动作，画面仍没变化。"
            '先用 {"type":"zoom",...} 放大确认当前勾选/焦点状态，再决定要不要点；'
            "**已经选中的选项不要再点**，点了会取消。"
        )

    # 自家界面的窗口标题特征：这些窗口永远不是演示目标
    # 只认自家的演示控制台；不要放 CodeMentor 之类，否则用户就是来演示这个应用时会被误伤
    OWN_UI_TITLES = ("屏幕演示控制台", "屏幕演示面板", "演示控制台", "屏幕演示 -")

    def _is_own_window(self, title: str) -> bool:
        t = (title or "").lower()
        return any(k.lower() in t for k in self.OWN_UI_TITLES)

    async def _make_room(self, runner: "Runner") -> str:
        """前台被自家控制台占着时先让开：点它等于白点，画面也不会动。

        这是实测踩过的坑：控制台浮在答题页上面，模型连点 13 下全部打在控制台上，
        每次都判"没变化"，然后继续换坐标——整轮演示就这么废了。
        """
        try:
            from app.screen_agent.actions import foreground_window, minimize_window

            info = await asyncio.to_thread(foreground_window)
        except Exception as exc:  # noqa: BLE001
            logger.debug("读前台窗口失败: %s", exc)
            return ""
        title = str(info.get("title") or "")
        if not title or not self._is_own_window(title):
            return ""

        ok = await asyncio.to_thread(minimize_window, int(info["hwnd"]))
        if not ok:
            return "⚠️ 前台是演示控制台（自家界面），点它会白白浪费一步；请先把它最小化再继续"
        await asyncio.sleep(0.45)
        return "（系统：演示控制台挡住了目标窗口，已自动最小化它，继续操作）"

    async def _run_knowledge(self, query: str) -> str:
        """查本地知识库（答题/查资料用）。结果作为取证回到下一帧的提示词里。"""
        query = (query or "").strip()
        if not query:
            return "查询为空"
        try:
            from app.core.state import state as app_state

            store = getattr(app_state, "store", None)
            if store is None:
                return "知识库未初始化（后端启动时 RAG 没起来），这次答题只能靠你自己的知识"
            hits = await store.search_knowledge(query, top_k=4)
            if not hits:
                return f"知识库没有「{query[:30]}」相关内容，改为用自己的知识判断"
            lines = []
            for hit in hits[:4]:
                text = str(hit.get("text") or "").replace("\n", " ")[:180]
                lines.append(f"[{float(hit.get('score') or 0):.2f}] {text}")
            return "命中：\n" + "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识库检索失败: %s", exc)
            return f"知识库检索失败（{exc}），用自己的知识判断"

    async def _run_web(self, action: dict[str, Any]) -> str:
        """联网搜索 / 读网页（答题时知识库没有的东西靠它）。"""
        try:
            from app.agent.tools import web as web_tool

            if action.get("type") == "web_open":
                url = str(action.get("url") or "")
                result = await web_tool.web_fetch(url, max_chars=1600)
                if not result.get("ok"):
                    return f"读网页失败：{result.get('error')}"
                text = str(result.get("text") or "").replace("\n", " ")
                return f"《{str(result.get('title') or url)[:40]}》{text[:900]}"

            query = str(action.get("query") or "")
            result = await web_tool.web_search(query, count=4)
            if not result.get("ok"):
                return f"联网搜索失败（{result.get('error')}），先用自己的知识判断"
            lines = []
            for item in (result.get("results") or [])[:4]:
                title = str(item.get("title") or "")[:50]
                snippet = str(item.get("snippet") or "")[:120]
                lines.append(f"- {title}：{snippet}")
            return "搜索结果：\n" + "\n".join(lines) + "\n（要细看某条就用 {\"type\":\"web_open\",\"url\":\"...\"} 打开）"
        except Exception as exc:  # noqa: BLE001
            logger.warning("联网失败: %s", exc)
            return f"联网失败（{exc}），先用自己的知识判断"
    async def _run_probe(self, probe: dict[str, Any]) -> str:
        """帧内取证：只读，不改变桌面。"""
        tool = str(probe.get("tool") or "").strip().lower()
        try:
            from app.screen_agent import uia
        except Exception as exc:  # noqa: BLE001
            return f"控件树不可用（{exc}）"

        if tool in ("controls", "tree", "uia"):
            res = await asyncio.to_thread(uia.probe, probe.get("title") or None)
            if not res.get("ok"):
                return f"读控件树失败：{res.get('error')}"
            lines = [f"窗口「{res['window']}」共 {res['count']} 个控件"]
            for it in res["items"][:24]:
                lines.append(f"[{it['index']}] {it['type']} '{it['name']}'")
            return "；".join(lines)

        if tool in ("windows", "list_windows"):
            wins = await asyncio.to_thread(uia.list_windows)
            return "；".join(w["title"][:40] for w in wins[:12]) or "没有可见窗口"

        if tool in ("read_file", "cat", "read"):
            from app.agent.tools import files as fs

            path = str(probe.get("path") or "").strip()
            if not path:
                return "read_file 需要 path（绝对路径）"
            res = await fs.read_file(path, lines=int(probe.get("lines") or 200))
            if not res.get("ok"):
                return f"读取失败：{res.get('error')}"
            raw = res.get("content") or ""
            body = raw if isinstance(raw, str) else "\n".join(str(x) for x in raw)
            return f"{path} 共 {res.get('total_lines', '?')} 行\n{body[:3000]}"

        if tool in ("list_dir", "ls", "tree"):
            from app.agent.tools import files as fs

            res = await fs.list_dir(str(probe.get("path") or ""), depth=int(probe.get("depth") or 1))
            if not res.get("ok"):
                return f"读取失败：{res.get('error')}"
            return "；".join(f"{i['name']}/" if i.get("type") == "dir" else i["name"]
                            for i in res.get("items", [])[:40])

        if tool in ("value", "read_value"):
            idx = int(probe.get("index") or 0)
            val, err = await asyncio.to_thread(uia.get_value, idx)
            return f"#{idx} 的内容：{val[:200]}" if val is not None else f"读不到：{err}"

        return f"未知取证工具：{tool}"

    async def _handle_uia(self, action: dict[str, Any], runner: "Runner"):
        """处理控件树类动作。返回 (是否已处理, 替换后的动作, 说明)。"""
        kind = action.get("type")
        try:
            from app.screen_agent import uia
        except Exception as exc:  # noqa: BLE001
            return True, None, f"控件树不可用（{exc}）"

        if kind == "controls":
            res = await asyncio.to_thread(uia.probe, action.get("title") or None)
            if not res.get("ok"):
                return True, None, f"读控件树失败：{res.get('error')}"
            lines = [f"【控件树 · {res['window']} · {res['count']} 个控件】"]
            for it in res["items"][:60]:
                x, y, w, h = it["rect"]
                lines.append(f"[{it['index']}] {it['type']} '{it['name']}' @ {x},{y} {w}x{h}")
            runner.controls_text = "\n".join(lines)
            runner.controls_window = res.get("window") or ""
            return True, None, f"读到「{res['window']}」{res['count']} 个控件（{res.get('elapsed_ms')}ms）"

        if kind == "click_control":
            info, err = await asyncio.to_thread(uia.centre, int(action["index"]))
            if info is None:
                return True, None, f"定位控件失败：{err}"
            return (
                False,
                {"type": "click", "x": info["x"], "y": info["y"]},
                f"点击控件「{info['name']}」({info['type']})",
            )

        if kind == "invoke_control":
            ok, msg = await asyncio.to_thread(uia.invoke, int(action["index"]))
            return True, None, msg

        if kind == "set_control":
            ok, msg = await asyncio.to_thread(uia.set_value, int(action["index"]), action.get("text", ""))
            return True, None, msg

        return False, None, ""

    @staticmethod
    def _zoom_around(action: dict[str, Any]) -> dict[str, float] | None:
        """以某个动作的坐标为中心，取一块占屏幕约 22% 的区域放大。"""
        x = action.get("x")
        y = action.get("y")
        if x is None or y is None:
            return None
        try:
            cx, cy = float(x), float(y)
        except (TypeError, ValueError):
            return None
        half_w, half_h = 110.0, 110.0
        return {
            "x0": max(0.0, cx - half_w),
            "y0": max(0.0, cy - half_h),
            "x1": min(1000.0, cx + half_w),
            "y1": min(1000.0, cy + half_h),
        }

    async def _execute_action(
        self, action: dict[str, Any], screen_size: tuple[int, int], dry_run: bool
    ) -> tuple[bool, str]:
        """统一执行入口（主流程与重试共用）。"""
        if dry_run:
            return True, f"[dry-run] 计划执行 {json.dumps(action, ensure_ascii=False)}"
        try:
            return True, await asyncio.to_thread(execute, action, screen_size)
        except ActionError as exc:
            return False, f"动作被拒绝：{exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"动作执行异常：{exc}"

    async def _judge_previous(
        self,
        runner: Runner,
        state: dict[str, Any],
        channel: str,
        session_id: str,
        same_frame: bool,
        screen_size: tuple[int, int] | None = None,
    ) -> str:
        """判定上一步动作。

        返回 "retried" 表示已经原地重试过（本轮不再问模型）；
        返回 "" 表示正常继续。
        策略：没反应 → 1.5 秒后重试一次 → 3 秒后重试一次 → 仍没反应 → 换方案。
        **任何情况下都不自动暂停**，只有模型出错才会中断。
        """
        pend = runner.pending
        if not pend:
            return ""
        runner.pending = None
        if state.get("dry_run"):
            return ""

        action = pend["action"]
        desc = describe_action(action)
        changed = not same_frame

        # 宽限期复查：界面可能只是还没刷新完
        if not changed:
            try:
                await asyncio.sleep(1.0)
                shot2 = await self.capture.grab()
                h2 = self.capture.signature(shot2["image"])
                if h2 and self.capture.diff_ratio(h2, runner.last_sig) >= 0.005:
                    changed = True
                    runner.last_sig = h2
            except Exception as exc:  # noqa: BLE001
                logger.debug("复查抓帧失败: %s", exc)

        # 只记失败，成功由 step done 触发（见下方 action["type"] == "step" 分支）
        if action.get("type") == "edit_line":
            try:
                from app.screen_agent import editor_profiles

                runner.edit_variant = editor_profiles.remember(
                    runner.app_scope, str(action.get("variant") or "home_end"), changed
                )
                if not changed:
                    logger.info("整行编辑没生效，下次换用 %s 手法", runner.edit_variant)
            except Exception:  # noqa: BLE001
                pass

        if changed:
            runner.retry_attempts = 0
            runner.fail_streak = 0
            runner.neutral_streak = 0
            runner.force_switch = False
            runner.zoom = None
            runner.last_click = None
            try:
                await record_lesson(
                    scope=pend.get("scope") or GLOBAL_SCOPE,
                    action=action,
                    outcome="success",
                    method=desc,
                    goal=state.get("goal", ""),
                )
            except Exception:  # noqa: BLE001
                pass
            return ""

        # 在编辑器里点一下只是放光标，画面几乎没有变化——这种不算失败，否则会陷入
        # 「点了没变化 → 换坐标再点」的死循环（IDEA 里连点同一行就是这个现象）
        soft_kinds = {"click", "double_click", "right_click", "type", "key", "hotkey", "move"}
        if action.get("type") in soft_kinds and runner.neutral_streak < 1:
            # 只放行一次，不写经验库（这不是失败，是"看不出差别"）
            runner.neutral_streak += 1
            await bus.publish(
                channel,
                {
                    "type": "notice",
                    "level": "info",
                    "message": f"「{desc}」画面看不出变化，但可能是光标/焦点变化，继续下一步",
                },
            )
            return ""

        # ---------------- 没反应：按 5s → 10s 升级重试，最后换方案 ----------------
        attempt = runner.retry_attempts
        if attempt == 1:
            # 第二次不再盲重点：放大刚才那块区域并标出上次点击的位置，让模型看清楚再决定
            runner.retry_attempts = 2
            runner.zoom = self._zoom_around(action)
            await bus.publish(
                channel,
                {
                    "type": "notice",
                    "level": "warning",
                    "message": f"「{desc}」还是没反应，放大刚才那块区域，重新确认位置再点",
                },
            )
            await asyncio.sleep(0.8)
            return ""

        if attempt < len(self.RETRY_DELAYS):
            wait = self.RETRY_DELAYS[attempt]
            runner.retry_attempts = attempt + 1
            await bus.publish(
                channel,
                {
                    "type": "notice",
                    "level": "warning",
                    "message": f"「{desc}」暂时没让界面变化，等 {int(wait)} 秒后原地重试一次",
                },
            )
            await asyncio.sleep(wait)
            if not runner.running.is_set() or runner.stopped:
                return "retried"

            ok, detail = await self._execute_action(
                action, screen_size or (1920, 1080), bool(state.get("dry_run"))
            )
            runner.pending = {
                "action": action,
                "key": pend["key"],
                "scope": runner.app_scope,
                "step": pend.get("step", 0),
            }
            await bus.publish(
                channel,
                {
                    "type": "notice",
                    "level": "info",
                    "message": f"已重试（第 {runner.retry_attempts} 次）：{detail or desc}",
                },
            )
            return "retried"

        # 三次都没反应 → 记为无效、强制换方案，但**不暂停**
        runner.retry_attempts = 0
        runner.fail_streak += 1
        runner.failed[pend["key"]] = desc
        runner.force_switch = True
        try:
            await record_lesson(
                scope=pend.get("scope") or GLOBAL_SCOPE,
                action=action,
                outcome="failure",
                method=desc,
                goal=state.get("goal", ""),
                note="重试 3 次画面仍无变化",
            )
        except Exception:  # noqa: BLE001
            pass
        await bus.publish(
            channel,
            {
                "type": "notice",
                "level": "warning",
                "message": f"「{desc}」等了 15 秒仍无变化，已弃用，接下来换一种做法",
            },
        )
        return ""

    # ------------------------------------------------------------------ 视觉决策
    @staticmethod
    async def _resolve_screen_model():
        """屏幕演示用哪个模型。

        默认自动挑多模态模型；也可以：
        - screen_share_chat_model=True  → 直接用对话侧那个模型（要求它支持图片）
        - screen_model_override="qwen:qwen3-vl-plus" → 显式指定
        """
        override = (getattr(settings, "screen_model_override", "") or "").strip()
        async with session_scope() as session:
            if override:
                provider, _, model = override.partition(":")
                resolved = await resolve_model(
                    session,
                    provider=provider.strip() or None,
                    model=model.strip() or None,
                    need_vision=True,
                )
                name = model.strip() or resolved.vision_model
                logger.info("屏幕演示使用指定模型: %s / %s", resolved.provider, name)
                return resolved, name

            if getattr(settings, "screen_share_chat_model", False):
                resolved = await resolve_model(session, need_vision=False)
                name = resolved.model or resolved.vision_model
                logger.info("屏幕演示与对话共用模型: %s / %s", resolved.provider, name)
                return resolved, name

            resolved = await resolve_model(session, need_vision=True)
            return resolved, resolved.vision_model

    async def _decide(
        self, state: dict[str, Any], image_data_url: str, runner: Runner, same_frame: bool = False
    ) -> dict[str, Any]:
        resolved, vision_name = await self._resolve_screen_model()

        mode_hint = MODE_HINTS.get(getattr(settings, "screen_mode", "demo"), "")
        try:
            from app.screen_agent.editors import render_shortcuts

            mode_hint += render_shortcuts(runner.app_scope)
        except Exception:  # noqa: BLE001
            pass

        def _build(thinking: bool | None):
            return build_chat_model(
                resolved,
                model_override=vision_name,
                streaming=False,
                temperature=0.1,
                max_tokens=settings.screen_max_tokens,
                thinking=thinking,
            )
        plan_steps = state["plan"]
        current = state["current_step"]
        plan_text = "\n".join(
            f"{'→' if i == current else ' '} {i + 1}. {s}" for i, s in enumerate(plan_steps)
        ) or "（无预设步骤，按目标自由操作）"

        history = "\n".join(runner.recent[-3:]) or "（这是第一步）"

        repeats = 1
        if len(runner.signatures) >= 2 and runner.signatures[-1] == runner.signatures[-2]:
            repeats = 2
            if len(runner.signatures) >= 3 and runner.signatures[-2] == runner.signatures[-3]:
                repeats = 3
        hint = "正常推进。"
        if repeats == 2:
            hint = "刚才这个动作没有让界面变化，这次请换一种方式（优先快捷键），不要再重复。"
        elif repeats >= 3:
            hint = "同一动作已连续 2 次无效，必须改用完全不同的做法，或先按 esc 回到稳定状态。"

        verify = ""
        if runner.last_type_text and current - runner.last_type_step <= 2:
            verify = (
                f"【输入自检】上一步输入的是：{runner.last_type_text[:60]}。"
                "请核对截图里的文字是否与之一致；如有全角字符/缺字，用 ctrl+a 全选后整段重输。\n"
            )

        if same_frame:
            verify += (
                "【画面未变化】当前截图与上一步完全一致，说明上一个动作没有产生可见效果，"
                "请换一种方式（优先快捷键），不要重复同样的点击。\n"
            )

        # 经验库：这个应用下哪些做法有效/无效（含用户教过的）
        prev_scope = runner.app_scope
        runner.app_scope = foreground_app()
        if prev_scope != runner.app_scope:
            runner.controls_text = ""
            runner.controls_window = ""
        lessons = await recall_lessons(runner.app_scope, limit=5)
        lessons_text = render_lessons(lessons, runner.app_scope)

        # 对话智能体看过的屏幕信息，也能反哺演示（它可能已经知道你刚才开着什么）
        chat_view = ""
        try:
            from app.screen_agent.context import get_observation, render_context

            chat_view = render_context(get_observation(int(state.get("user_id") or 1)))
        except Exception:  # noqa: BLE001
            chat_view = ""

        blocked_text = ""
        if runner.failed:
            blocked_text = "【本次已失效·禁止再用】\n" + "\n".join(
                f"- {desc}" for desc in list(runner.failed.values())[-6:]
            ) + "\n"

        if runner.force_switch:
            blocked_text += (
                "【必须换方案】刚才那个做法等了 15 秒界面都没反应，已经作废。\n"
                "这一次**不要再做类似的动作**：换快捷键、换入口（win+r / ctrl+l 输路径 / 开始菜单搜索）、"
                "或先按 esc 回到稳定状态再走别的路线。\n"
            )
            runner.force_switch = False

        prompt = (
            f"【演示目标】{state['goal']}\n"
            + (
                "【用户明确指示 · 最高优先级 · 必须遵守】\n"
                + "（下表是用户亲口定的规则，优先级高于经验库、快捷键习惯和你的默认做法；"
                "违反它 = 这一步做错了）\n"
                + "\n".join(f"- 用户原话：{a['answer']}" for a in runner.answers[-4:])
                + "\n"
                if runner.answers
                else ""
            )
            + (
                "【必须动手 · 禁止提问】上面这些指示已经足够，这一次必须输出一个具体动作"
                "（click / type / key / sequence / wait 等），不允许再输出 ask。\n"
                if runner.force_act and runner.answers
                else ""
            )
            + (
                "【别把自己的控制面板当成目标】截图里如果出现标题含「屏幕演示」「屏幕演示控制台」"
                "或「演示暂停，需要你回答」的窗口/面板，那都是本项目自己的界面："
                "不要点击它们、不要把它们的文字当成学习者应用里的内容。\n"
            )
            + f"【当前前台程序】{runner.app_scope}\n"
            + (
                "【画面状态 · 重要】这一帧与上一帧**像素完全相同**（已连续 "
                f"{runner.same_frame_streak} 帧没变化）。\n"
                "说明你上一步操作**没有生效**，而不是「画面变成了别的东西」。\n"
                "所以：不要描述任何新出现的界面/文字（那是上次就有的），"
                "也不要重复上一次的动作；请换一种做法（换坐标、换快捷键、先确认窗口真的在前台）。\n"
                if runner.same_frame_streak >= 1
                else ""
            )
            + (
                "【任务清单】\n"
                + "\n".join(
                    f"{i+1}. [{'进行中' if x['status']=='doing' else ('已完成' if x['status']=='done' else ('已放弃' if x['status']=='skip' else '待办'))}] {x['title']}"
                    for i, x in enumerate(runner.checklist)
                )
                + "\n（只做「进行中」那一条；做完用 {\"type\":\"step\",\"index\":1,\"status\":\"done\"} 标记）\n"
                if runner.checklist
                else ""
            )
            + (
                f"【控件树】\n{runner.controls_text}\n"
                "（用 click_control / set_control / invoke_control 带 index 操作）\n"
                if runner.controls_text
                else ""
            )
            + f"【当前视角】{'放大观察中，坐标仍按全屏 0~1000 给' if runner.zoom else '全屏'}\n"
            f"【预设步骤】（参考路线，→ 是当前进度；走不通可以跳过或换路线）\n{plan_text}\n"
            f"【当前进度】第 {current + 1} 步（上限 {state['max_steps']} 步）\n"
            f"【最近操作】\n{history}\n"
            f"【提醒】{hint}\n"
            f"{blocked_text}"
            f"{lessons_text}"
            f"{chat_view}"
            f"{verify}"
            + (
                "【本帧查到的外部信息】\n"
                + "\n".join(runner.frame_context[-6:])
                + "\n（这些是系统真实查到的：控件树 / 知识库 / 联网结果，优先采信它们，别凭空猜）\n"
                if runner.frame_context
                else ""
            )
            + "截图上方与左侧是 0~1000 的坐标刻度，点击请按刻度估位。现在输出下一步动作 JSON。"
        )
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        )
        try:
            from app.rag.guides import guide_context

            guide_text = await guide_context("screen")
        except Exception:  # noqa: BLE001
            guide_text = ""
        system_text = SYSTEM_PROMPT + ("\n" + guide_text if guide_text else "")

        try:
            resp = await _build(False).ainvoke(
                [SystemMessage(content=system_text + mode_hint), message]
            )
        except Exception as exc:  # noqa: BLE001  个别模型不认 enable_thinking，退回普通调用
            logger.info("视觉模型带 enable_thinking 调用失败，退回默认参数: %s", exc)
            resp = await _build(None).ainvoke(
                [SystemMessage(content=system_text + mode_hint), message]
            )
        text = resp.content if isinstance(resp.content, str) else str(resp.content or "")
        return parse_action_json(text)

    # ------------------------------------------------------------------ 辅助
    async def _set_status(self, session_id: str, status: str) -> None:
        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is not None:
                row.status = status
                row.updated_at = utcnow()
                if status in ("completed", "failed"):
                    row.ended_at = utcnow()
                await session.commit()

    async def _finish(self, session_id: str, message: str) -> None:
        IME_GUARD.restore_all()
        await self._set_status(session_id, "completed")
        await bus.publish(
            f"screen:{session_id}",
            {"type": "done", "status": "completed", "message": message},
        )

    async def _fail(self, session_id: str, message: str) -> None:
        IME_GUARD.restore_all()
        async with session_scope() as session:
            row = await session.get(ScreenSession, session_id)
            if row is not None:
                row.status = "failed"
                row.last_error = message
                row.updated_at = utcnow()
                row.ended_at = utcnow()
                await session.commit()
        await bus.publish(
            f"screen:{session_id}", {"type": "error", "status": "failed", "message": message}
        )

    @staticmethod
    def _serialize(row: ScreenSession) -> dict[str, Any]:
        return {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "goal": row.goal,
            "plan": list(row.plan or []),
            "status": row.status,
            "interval_ms": row.interval_ms,
            "max_steps": row.max_steps,
            "current_step": row.current_step,
            "dry_run": row.dry_run,
            "provider": row.provider,
            "model": row.model,
            "last_error": row.last_error,
        "pending_question": row.pending_question,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "gui_available": GUI_AVAILABLE,
        }

    @staticmethod
    def _serialize_step(row: ScreenStep) -> dict[str, Any]:
        return {
            "id": row.id,
            "idx": row.idx,
            "thought": row.thought,
            "action": row.action,
            "status": row.status,
            "detail": row.detail,
            "screenshot": row.screenshot,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
