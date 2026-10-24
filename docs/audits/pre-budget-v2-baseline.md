# 野渡寻踪 V2 · 阶段 0：项目保护与真实运行基线

> 报告路径：`docs/audits/pre-budget-v2-baseline.md`
> 执行日期：2026-10-16
> **版本：v2（含补充验证轮）** —— 第二轮专门关闭了首轮 C 组的未验证项，详见「附录 B」
> 阶段目标：**不开发新功能**，建立可靠基线并验证现有功能的真实运行情况
> 执行边界：未修改业务代码、未重构、未换地图、未安装依赖、未开发预算功能、未自行设计页面

---

## 〇、方法与证据边界

| 结论类型 | 本报告的判定方式 |
|---|---|
| **实测通过** | 用真实浏览器（Playwright + Chromium）完成交互，观察到预期结果 |
| **实测失败** | 同上，观察到明确的错误结果（含错误码/降级文案/DOM 证据） |
| **部分通过** | 流程走通但结果不完整，或被测试节奏影响未取到最终态 |
| **未验证** | 因前置条件不满足（如依赖登录、依赖前一步产物）未能执行 |
| **代码表明可行** | 仅通过源码分析得出，本次未在浏览器中执行 |

**已执行的验证手段**：Playwright 真实浏览器交互（桌面 1440×900 / 移动 390×844）、
真实 HTTP 请求、后端函数直调、SQLite 直查、`grep` 全项目检索、Dockerfile/依赖/环境变量核对、
导出文件落盘校验。

**未执行**：真实用户行为测试、多用户并发、跨浏览器（只测了 Chromium）、
线上 HF Space 与 CF Pages 的端到端验证（**本报告所有结论均为本地环境**）。

### ⚠️ 本报告更正了三个阶段 0 之前的错误结论

审计纪律要求：**旧结论不得当作本次已实测**。本次推翻了以下先前记录：

| 先前结论 | 本次实测 | 说明 |
|---|---|---|
| 「`next dev` 会 404，必须用静态 `out/`」 | **错误**。`npm run dev` 正常，`/`、`/recommend`、`/trip` 全部 200 | 已用项目自带命令复现 |
| 「`/trip` 页面完全空白」 | **测试方式造成的假象**。真实原因是未登录时它**正常跳转 `/login`** | 见 §C1 |
| 「React 未 hydration → 应用不可交互」 | **测试方式造成的假象**。用 `127.0.0.1:3000` 访问会被 Next 16 拦截 dev 资源；改用 `localhost:3000` 后 22/22 元素挂上 React fiber | 见 §2.3 环境注意事项 |
| 「景点照片接口全部 404 不可复现」 | **是我自己掩盖了缺陷**：我的探针手动加了 `http://localhost:8000` 前缀。前端实际用的是相对路径 → **必然 404，已在浏览器复现** | 见 §6 问题 1 |

---

## 一、Git 基线状态及备份结果

### 1.1 当前状态

| 项 | 值 |
|---|---|
| 仓库 | `<repo-root>`（是 git 仓库） |
| 当前分支 | **`master`**（未切换） |
| HEAD | **`537e670083f59e692f13c1ae890deb411c54de93`** |
| HEAD 时间 | 2026-10-11 21:19:47 +0800 |
| HEAD 提交 | `fix(images): 429 限流显式化 + 图片下载失败原因可读` |
| 远端 | `origin` → `https://github.com/caozhi-hh/yeduxunzhong.git`；另一个 HF Space 远端（凭据内嵌于 `.git/config`，本报告不展示） |

### 1.2 ⚠️ 工作区不干净 → 按规则停止一切 Git 写入

`git status --porcelain` 返回 **25 条**（18 个已修改 + 7 项未跟踪）。

**按任务规则第 4 条：「如果存在未提交改动，停止 Git 写入操作，报告哪些内容尚未受到提交保护」。**
因此**本次未执行任何 git 写操作**：未创建 `backup/pre-budget-v2` 分支、未提交、未 stash、未 reset、未 clean、未切换分支。

### 1.3 未受提交保护的内容清单（约 2,400 行）

**已修改但未提交（18 个文件）**

| 文件 | 行数 | 改动量 |
|---|---|---|
| `backend/main.py` | 1054 | +238 / -0 |
| `frontend/src/lib/api.ts` | 445 | +244 / -0 |
| `frontend/src/app/recommend/page.tsx` | 969 | +171 / -163 |
| `frontend/src/app/page.tsx` | 128 | +99 / -112 |
| `frontend/src/app/globals.css` | 156 | +149 / -12 |
| `frontend/src/app/plan/page.tsx` | 562 | +60 / -52 |
| `backend/database.py` | 104 | +51 / -1 |
| `frontend/src/app/layout.tsx` | 45 | +22 / -19 |
| `frontend/package-lock.json` | 8271 | +252 / -1 |
| `frontend/src/app/login/page.tsx` | 223 | +21 / -21 |
| `frontend/src/components/PlanCard.tsx` | 83 | +11 / -11 |
| `frontend/src/app/history/page.tsx` | 109 | +10 / -10 |
| `frontend/src/i18n/locales/zh.json` | 91 | +9 / -9 |
| `frontend/src/i18n/locales/en.json` | 91 | +9 / -9 |
| `frontend/src/components/RouteMap.tsx` | 169 | +7 / -7 |
| `frontend/src/components/UserNav.tsx` | 63 | +5 / -5 |
| `backend/tools/images.py` | 671 | +5 / -2 |
| `frontend/package.json` | 39 | +4 / -0 |

**完全未跟踪（7 项）—— 这些文件只存在于本机磁盘**

| 路径 | 规模 |
|---|---|
| `backend/tools/poi.py` | 266 行 |
| `backend/tools/photos.py` | 244 行 |
| `backend/tools/websearch.py` | 143 行 |
| `backend/trips.py` | 282 行 |
| `frontend/src/app/trip/page.tsx` | 1003 行 |
| `frontend/src/components/SiteHeader.tsx` | 96 行 |
| `frontend/src/components/ui/`（8 个文件） | 424 行 |

**风险**：真实地点层（POI）、地点照片层、攻略搜索层、结构化行程模块、整个 `/trip` 页、
9 个 UI 组件与设计 token —— **全部没有版本保护**。任何 `git checkout .` / `git clean -fd` /
换机器操作都会造成不可逆丢失。

### 1.4 环境变量配置状态（只报名称与配置状态，不输出任何值）

| 变量名 | 在 `backend/.env` | 进程环境 | 源码硬编码兜底 | 备注 |
|---|---|---|---|---|
| `ZHIPU_API_KEY` | — | — | **有（已进 git 历史）** | 对话模型密钥 |
| `ZHIPU_BASE_URL` | — | — | 有 | |
| `CHAT_MODEL` | — | — | 有（`glm-4-flash`） | 项目注释标注为**免费档** |
| `UNSPLASH_ACCESS_KEY` | — | — | **有（已进 git 历史）** | |
| `PIXABAY_API_KEY` | **有** | 有 | 无 | 当前生效图源 |
| `AMAP_WEB_KEY` | — | — | **有（已进 git 历史）** | **key 已回收**，见 §6 |
| `TAVILY_API_KEY` | **有** | 有 | 无 | 地点照片/攻略搜索 |
| `JWT_SECRET` | — | — | 无 | 落盘 `backend/.jwt_secret`（已 gitignore） |
| `TRAVEL_DB_PATH` | — | — | 无 | 可选覆盖数据库路径 |

**忽略规则核实**（用 `git check-ignore -v` 精确验证，非靠返回值猜）：

| 文件 | 结论 | 命中规则 |
|---|---|---|
| `backend/.env` | ✅ 已忽略 | `.gitignore:4:.env` |
| `frontend/.env.local` | ✅ 已忽略 | `frontend/.gitignore:34:.env*` |
| `backend/.jwt_secret` | ✅ 已忽略 | `.gitignore` 显式条目 |
| `frontend/.env.production` | ⚠️ **已被 git 跟踪** | 未被任何规则匹配 |

`frontend/.env.production` 内含 `NEXT_PUBLIC_AMAP_KEY`（32 字符）与 `NEXT_PUBLIC_AMAP_SECRET`（31 字符）。
这两个值是 `NEXT_PUBLIC_*`，本身就会打进浏览器包，**但公开仓库中出现高德密钥与安全密钥是实质暴露**——
高德官方对公开泄露的 key 会执行回收，这与 §6 问题 3 中 key 状态为 `USER_KEY_RECYCLED` 的现象一致
（**因果为合理推断，非本次实测结论**）。
同时 `backend/config.py` 与根目录 `config.py` 的**已提交版本**中含 5 个 / 4 个硬编码密钥默认值
（含 `ZHIPU_API_KEY`、`UNSPLASH_ACCESS_KEY`、`AMAP_WEB_KEY`、`ARK_API_KEY`），**已进入 git 历史**。

---

## 二、前后端启动情况

### 2.1 项目自带启动入口（源码实证）

| 脚本 | 实际命令 |
|---|---|
| `本地-后端.bat` | `cd backend` → `python -m uvicorn main:app --host 127.0.0.1 --port 8000` |
| `本地-前端.bat` | `cd frontend` → `npm run dev`（即 `next dev`） |
| `本地预览-一键启动.bat` | 先 kill 8000/3000 端口进程 → 分别启动前后端 → 等 35 秒 → 打开 `http://localhost:3000` |
| 根 `Dockerfile`（线上） | `python:3.11-slim` + `backend/requirements.txt` → `uvicorn main:app --port 7860` |

### 2.2 本次启动实测

| 项 | 结果 |
|---|---|
| 后端 `python -m uvicorn main:app --host 127.0.0.1 --port 8000` | ✅ 启动成功，`/openapi.json` 返回 **200（27,321 字节，26 条路由）** |
| 前端 `npm run dev` | ✅ 启动成功，"Ready in 6.6s"；`/` 200（20,909 字节）、`/recommend` 200、`/trip` 200 |
| 启动耗时 | 后端约 40–60 秒（依赖导入较重）；前端 6.6 秒 |

### 2.3 ⚠️ 环境注意事项（本次踩到，会影响后续所有测试）

**必须用 `http://localhost:3000` 访问前端，不能用 `http://127.0.0.1:3000`。**

Next.js 16 默认拦截来自非允许来源的 dev 资源。用 `127.0.0.1` 访问时后端日志报：

```
⚠ Blocked cross-origin request to Next.js dev resource /_next/webpack-hmr from "127.0.0.1".
To allow this host in development, add it to "allowedDevOrigins" in next.config.js
```

后果：**页面 HTML 正常返回、React 也加载了，但 hydration 永远不完成 → 所有按钮点击无效**。
实测对比（同一台机器、同一份代码）：

| 访问地址 | 可交互元素 | 挂上 React fiber 的 | 结论 |
|---|---|---|---|
| `http://127.0.0.1:3000` | 22 | **0** | 未 hydration，页面是死壳 |
| `http://localhost:3000` | 22 | **22** | ✅ 完全可交互 |

**这不是产品缺陷**，是 dev 环境访问方式问题。但因为它会让「一切点击都无反应」且**控制台没有 hydration 报错**，
极易被误判为严重产品故障（本次即误判过一次）。建议在 `next.config.ts` 中补 `allowedDevOrigins`，
或至少在 README/交接文档中写明。

### 2.4 AI 调用与费用

- 实际模型：`CHAT_MODEL = glm-4-flash`（`backend/config.py:31`）
- 项目自身注释（`backend/config.py:27`）：**"新 key 为免费档 → 主对话用 glm-4-flash"**
- 本次为验证而触发的 AI 调用共 **3 次生成类**：`/api/recommend` 1 次、`/api/generate-plan` 2 次、`/api/modify` 1 次
- 未调用任何本次新引入的付费接口；未产生计费型调用

---

## 三、每个功能的实测结果

图例：✅ 实测通过　❌ 实测失败　🟡 部分通过　⬜ 未验证

### A. 首页与导航

| 项 | 结果 | 证据 |
|---|---|---|
| 首页正常打开 | ✅ | 标题「野渡寻踪」，正文 235 字，无 404 文案，页面错误 0 |
| 「开始生成攻略」入口 | ✅ | 点击后 URL → `http://localhost:3000/recommend` |
| 桌面布局（1440×900） | ✅ | `scrollWidth=1440 = clientWidth=1440`，**无横向溢出** |
| 移动布局（390×844） | ✅ | `scrollWidth=390 = clientWidth=390`，**无横向溢出**，正文 227 字 |
| 空白/404/运行时错误 | ✅ 无 | `pageerror` 0 条；无 404 文案 |

### B. AI 攻略生成

| 项 | 结果 | 证据 |
|---|---|---|
| 页面可交互（hydration） | ✅ | 20 个按钮挂载 React fiber |
| 步骤 1 目的地 | ✅ | 点击城市芯片「成都」→「下一步」由禁用变可用 |
| 步骤 2 时间 | ✅ | 点击日期预设「暑假出行」→ 通过校验进入第 3 步（`depDate && retDate`） |
| 步骤 3 预算 | ✅ | 可进入第 4 步（预算滑块保持默认） |
| 步骤 4 偏好 | ✅ | 点选风格卡后可进入第 5 步 |
| 到达「开始推荐」 | ✅ | 按钮可用并成功触发 |
| **SSE 流式响应** | ✅ | 正文长度阶梯增长：`110 → 423 → 643`（0–45 秒采样），证明是分块流式而非一次性返回 |
| 景点推荐结果解析 | ✅ | 「勾选你想去的景点（已找到 **9** 个）」；可见景点名含 宽窄巷子/武侯祠/杜甫草堂/锦里/大熊猫 |
| 景点选择控件形态 | ✅（已摸清） | **不是 checkbox**，而是 **9 个可点击卡片**（`[class*="cursor-pointer"]` 恰为 9） |
| 勾选并生成攻略 | 🟡 | 成功跳转 `/plan`，但本次采样时正文仅 206 字（真实生成需 ~45 秒，采样过早）；`/api/generate-plan` 返回 200 |
| 景点配图 | ❌ | **9 张图片请求全部 404**（见 §6 问题 1） |

### C. 行程编辑（`/trip`）

| 项 | 结果 | 证据 |
|---|---|---|
| 未登录访问 `/trip` | ✅ 正常 | 重定向到 `/login`（正文 83 字），**不是空白页** |
| 经 UI 登录（`tripdemo`） | ✅ | 登录后 `localStorage` 出现 `yedu_auth_token`，页面标题含「首页 开始规划」 |
| `/trip` 加载 | ✅ | 正文 328 字；标题「野渡寻踪 · 行程规划」「新建行程」「我的行程 (4)」「地图」；7 个按钮；输入框 `["目的地，例如 拉萨", ...]` |
| 打开行程后出现 POI 搜索框 | ✅ | 点击「拉萨行程 3 个地点」后搜索框渲染。**上一轮失败正是因未做这一步**（脚本缺陷） |
| 搜索真实地点并加入 | ✅ | 搜「大昭寺」→ 页面出现 2 个「加入」按钮 → 点击后 Day1 地点数 **3 → 4**，新条目为 `大昭寺 ཇོ་ཁང།` |
| 跨天拖拽地点 | ✅ | 用 HTML5 `dragstart/dragover/drop` 事件序列：布达拉宫 **Day1 → Day2**，总数保持 4；**且已写入 SQLite**（库中 `布达拉宫` 所在 `day_index = 1`） |
| 刷新后**数据**仍在 | ✅ | 刷新后重新打开行程，库侧数据完整：trip 6 共 **4 个地点**，Day1 3 个 + Day2 1 个 |
| 刷新后**视图**自动恢复 | ❌ **不恢复** | `trip/page.tsx` 中 **localStorage 使用 0 次**、无 URL 参数、无"上次行程 id" → 刷新后页面回到"未打开任何行程"。**数据没丢，但用户需重新点开行程**（新发现，见 §6 其他问题） |
| 同城过滤按预期生效 | ✅ | 用**拉萨行程**搜成都的「宽窄巷子」→ 结果被 300km 离群过滤正确挡掉（0 个加入按钮）；换搜同城「大昭寺」→ 正常返回。**这是过滤器按设计工作，不是缺陷** |

### D. 地图

| 项 | 结果 | 证据 |
|---|---|---|
| **Leaflet（新）显示** | ✅ | `.leaflet-container` 存在，尺寸 **1096×420 px**，**已加载 15 张瓦片**（`img.leaflet-tile`）|
| 瓦片来源可达 | ✅ | `basemaps.cartocdn.com/.../11/1541/846.png` 等 **全部 200** |
| **高德地图（旧）** | ❌ **失败** | AMap SDK 脚本已注入（`webapi.amap.com` 存在）但 **`window.AMap === false`**、无 `.amap-container`、无 canvas，且页面显示组件自身的降级文案「地图加载失败」 |
| 坐标是否来自真实 POI | ✅（限于 `/trip`） | `trip_places` 表中 `source=openstreetmap`，如 布达拉宫 `(29.657905, 91.117398)`、天安门 `(39.907359, 116.391263)` |
| 地点坐标来自真实 POI | ✅ | 加入的 `大昭寺 ཇོ་ཁང། (29.65286, 91.131798)`、`布达拉宫 (29.657905, 91.117398)`、`八廓街道 (29.651687, 91.131348)` 全部 `source=openstreetmap`，坐标与真实位置一致 |
| 地图标记数 | ✅ | 加入后 `.leaflet-marker-icon` = **4**，与库中 4 个地点一致；瓦片 15 张 |
| 坐标是否存在异常 | ❌ **存在** | 库中仍有 `大昭寺 (43.998108, 143.749262)` —— **日本北海道**（见 §6 问题 5 |
| 旧高德是否影响主流程 | 🟡 | 影响 `/plan` 的地图展示（降级为「地图加载失败」），**不影响** `/recommend` 与生成流程 |

### E. 现有附加功能

| 项 | 结果 | 证据 |
|---|---|---|
| 攻略正文渲染 | ✅ | 注入真实 5730 字攻略（取自 SQLite）→ 渲染 5614 字，含 `Day 1/Day 2` 标题、门票预约提醒、费用明细 |
| **Markdown 表格渲染** | ❌ **失败** | 真实输出含 **6 个 markdown 表格**（50 行含 `\|`），但页面 `<table>` 数量为 **0** —— 表格退化为带竖线的纯文本，见 §6 问题 2 |
| 多轮对话修改 | ✅ | 点击「太累了，行程松一点」→ 正文 `5614 → 5900` 字，`/api/modify` 返回 **200** |
| 快捷调整入口 | ✅ | 6 个按钮全部存在（太累了/预算超了/加几个景点/换个玩法/带小孩/当地美食） |
| **Word 导出** | ✅ | 下载到 `野渡寻踪-旅行攻略.docx`，**42 KB**（落盘校验通过） |
| 历史记录 | ✅ | `/history` 正常加载；当前账号显示「还没有历史攻略」（该账号确实无记录，属正确行为） |
| 景点照片加载 | ❌ | 见 §6 问题 1 |
| 限流观察 | 🟡 | 本轮 429 = 0；但**前一轮因连续登录被 429 拦截**（登录 5 次/分） |

**截图与日志产物**（`ops/screenshots-baseline/`）：

首轮：`A-home-desktop.png` / `A-home-mobile.png` / `B-step2.png` / `B-step5.png` / `B-recommend-result.png` /
`B3-spots.png` / `B3-plan.png` / `C-trip-guest.png` / `C-trip-loaded.png` / `C-trip-search.png` /
`C-trip-final.png` / `D-amap.png` / `E-plan-render.png` / `E1-modify.png` / `E-history.png` /
`E-login-focus.png` / `hydration-probe.png` / `step1-micro.png`

补充轮（第二轮）：`C5-trip-opened.png` / `C6-trip-searched.png` / `C7-trip-drag.png` /
`C8-trip-after-reload.png` / `C9-trip-with-places.png` / `C10-trip-added.png` /
`C11-trip-dragged.png` / `C12-trip-after-reload.png`

**导出文件** `export-野渡寻踪-旅行攻略.docx`

后端/前端日志：`ops/baseline-be.log` / `ops/baseline-be.err` / `ops/baseline-fe-dev.log` / `ops/baseline-fe-dev.err`

---

## 四、测试证据明细（关键操作 → 实际结果）

| # | 操作 | 实际结果 |
|---|---|---|
| 1 | 用 `127.0.0.1:3000` 打开 `/recommend` 并点击城市芯片 | 点击无反应；`elementFromPoint` 命中自身（无覆盖层）；22 个可交互元素 **0 个**有 React fiber |
| 2 | 查后端日志 | 发现 `Blocked cross-origin request to Next.js dev resource ... from "127.0.0.1"` |
| 3 | 改用 `localhost:3000` 重复同一操作 | 22 个可交互元素 **22 个**有 fiber；点击城市芯片成功，按钮由禁用转可用 |
| 4 | Step2 用原生 setter 填 `"2026-11-01"` | 校验不通过；原因：输入框是 `datetime-local`，需 `YYYY-MM-DDTHH:mm` 格式（**测试数据错误**） |
| 5 | Step2 改点「暑假出行」预设 | 通过校验并进入第 3 步 |
| 6 | 完整走到「开始推荐」并采样正文长度 | `110 → 423 → 643`（阶梯增长 = 流式） |
| 7 | 观察景点区 DOM | `checkbox=0`，但 `cursor-pointer` 卡片 = 9，标题「已找到 9 个」（**控件形态与我的假设不同，非缺陷**） |
| 8 | 点击「生成攻略」 | 跳转 `/plan`，`/api/generate-plan` 200 |
| 9 | 记录所有 `/api/` 请求 | `/api/spot-images` 200，紧随其后的 9 个图片请求为 **`http://localhost:3000/api/images/...` 全部 404** |
| 10 | 用**带 `http://localhost:8000` 前缀**的探针复测同一批图片 | 全部 200（换新城市「张掖」5/5 成功）→ **证明缺陷源于前端未补 API_BASE，而非后端缺文件** |
| 11 | 读 `frontend/src/lib/api.ts:1` 与 `recommend/page.tsx:200/736` | `API_BASE` 只用于 API 请求；`spot.image = img.image_url`（相对路径）直接进 `<img src>` |
| 12 | 读 `next.config.ts` | 只有 `output:"export"` 与 `images.unoptimized`，**无 rewrites/proxy** |
| 13 | 注入真实 5730 字攻略到 localStorage 并加载 `/plan` | 渲染 5614 字；`<table>` 数量 **0** |
| 14 | 查 `plan/page.tsx:418` 与 `package.json` | 裸 `<ReactMarkdown>`，**无 remark-gfm 依赖** → GFM 表格不解析 |
| 15 | 点击「太累了，行程松一点」 | `/api/modify` 200，正文 5614 → 5900 字 |
| 16 | 点击「Word」导出 | 下载 `野渡寻踪-旅行攻略.docx`，42 KB |
| 17 | 注入真实坐标加载 `/plan` 并等待 9 秒 | AMap 脚本已加载但 `window.AMap=false`，组件显示「地图加载失败」 |
| 18 | 直调高德地理编码接口 | `status=0`、`info=USER_KEY_RECYCLED`、`infocode=10013`、`geocodes=0` |
| 19 | 直调 `/api/auth/login`（5 次不同组合） | `tripdemo/demo12345` → 200 + token；密码错误 → 明确错误文案；第 6 次触发 **429「请求过于频繁，请 60 秒后再试」** |
| 20 | 读 `rate_limiter.py` | 登录 **5 次/60 秒**、全局 API **30 次/60 秒**（内存级、按 IP） |
| 21 | 直查 SQLite | `plans` 78 行、`trips` 7 行、`trip_days` 18 行、`trip_places` 13 行、`users` 5 行 |
| 22 | 统计 `plans.user_type` 取值 | **78 行全部为 `'🎒 学生'`（含 emoji）** |
| 23 | 直查 `trip_places` | 存在 `大昭寺 (43.998108, 143.749262)`= 日本；`source` 全为 `openstreetmap` |

**补充验证轮（第二轮）新增证据**

| # | 操作 | 实际结果 |
|---|---|---|
| 24 | 未先打开行程就直接找 POI 搜索框 | 搜索框不存在（输入框仅 `["目的地，例如 拉萨","",""]`）→ 确认首轮失败是**脚本缺陷** |
| 25 | 点击「拉萨行程 3 个地点」后再找 | 搜索框渲染成功；Day 列显示 `布达拉宫 / 大昭寺 / 八廓街道` |
| 26 | 用拉萨行程搜成都的「宽窄巷子」 | **0 个「加入」按钮** → 被后端 300km 离群过滤正确挡掉（按设计工作） |
| 27 | 改搜同城「大昭寺」 | 页面命中 `大昭寺/八廓/布达拉宫`；出现 **2 个「加入」按钮** |
| 28 | 点击「加入」 | Day1 地点数 **3 → 4**，新增条目 `大昭寺 ཇོ་ཁང།` |
| 29 | 检查地图 | `.leaflet-marker-icon` = **4**（与库中地点数一致），瓦片 **15** 张，容器 1096×420 |
| 30 | 用 `DragEvent(dragstart/dragover/drop)` 把布达拉宫拖到第 2 天 | Day1 `4 → 3` 项、Day2 `0 → 1` 项；**总数保持 4** |
| 31 | 刷新页面 | 地图标记 **0**、Day 列空 → 视图未恢复（无 localStorage/URL 记忆） |
| 32 | 直查 SQLite 核对是否真丢数据 | **trip 6 共 4 个地点；`布达拉宫` 的 `day_index = 1`（即第 2 天）** → **数据已落盘，未丢失** |
| 33 | 读 `trip/page.tsx` 的持久化手段 | `localStorage` 出现 **0 次**；无 `useSearchParams`/`router.push`；无"上次行程 id" → 视图状态确实不持久 |
| 34 | 统计本轮 API 调用 | **27 次 / 0 次 429**（上限 30 次/60 秒，已接近触顶）；期间图片 404 再复现 **4 次** |

---

## 五、两套行程流程的数据流对比

### 5.1 流程一：`/recommend → /plan`（AI Markdown 攻略链路）

```
用户填表（全部为前端硬编码选项）
        │  POST /api/recommend  { params, session_id }
        ▼
main.py:434  拼接 prompt（budget / user_type / travel_type 仅作为【文字】注入）
main.py:447  get_weather(to_city)            ← ✅ 真实数据（wttr.in，免 key）
main.py:401  llm.stream(messages)            ← 流式产出 markdown
        │  SSE {"type":"chunk"}
        ▼
前端逐字渲染
        │  流结束
main.py:460  extract_spots_from_text(全文)   ← ⚠️ 正则解析模型输出
main.py:461  extract_spot_details(全文)      ← ⚠️ 正则解析
main.py:462  geocode_spots(spots, city)      ← ⚠️ 再调一次 LLM「猜」经纬度（实测 3 点 86.5 秒）
        │  SSE {"type":"done", spots, spot_details, coords}
        ▼
前端渲染 9 张景点卡片（点击卡片勾选）
        │  写入 localStorage：yedu_spot_coords
        │  用户勾选 → POST /api/generate-plan
        ▼
main.py:487  拼接 prompt + main.py:526 天气注入 + llm.stream  ← 全篇攻略（费用表为模型估算）
        ▼
/plan 页：ReactMarkdown 渲染 + RouteMap（高德）
        │  前端写入 localStorage：yedu_plan / yedu_selected_spots / yedu_user_params / yedu_to_city / yedu_session_id
        ▼
登录用户额外：POST /api/history  →  SQLite plans 表（plan_text 为一个大文本字段）
```

### 5.2 流程二：`/trip`（结构化行程 + 真实地点）

```
登录（必需，/api/trips 走 get_current_user）
        │  POST /api/trips { city, days }     → SQLite trips
        ▼
GET /api/trips                          ← 行程列表（前端左侧栏）
POST /api/trips/{id}/days               ← SQLite trip_days
        ▼
POST /api/poi/search { query, near_lat, near_lon, max_km }
        │  tools/poi.py → Photon(OSM)    ← ✅ 真实数据，免 key
        │  tools/photos.py → Tavily 图选 → 下载到本机自托管
        ▼
用户点「加入」→ POST /api/trips/days/{day_id}/places
        │  写入 SQLite trip_places（name/lat/lon/address/kind/source/sort_order）
        ▼
POST /api/trips/places/{id}/move        ← 跨天拖拽（重排 sort_order）
        ▼
Leaflet 地图：三底图可切 + GCJ-02 纠偏 + 视野自适应（坐标来自 OSM 真实值）
```

### 5.3 逐项对比

| 问题 | 流程一 `/recommend → /plan` | 流程二 `/trip` |
|---|---|---|
| **保存哪些数据** | 景点名数组、坐标、完整攻略文本、用户参数 | 行程 → 天 → 地点（三级结构），每个地点含 name/lat/lon/address/kind/source/sort_order |
| **数据结构是否一致** | ❌ **完全不一致**。前者是**一个 markdown 大文本 + 名字数组**；后者是**结构化三元组** | 同左 |
| **`/trip` 能否复用 `/recommend` 的结果** | ❌ **不能（代码层面无任何衔接）**：<br>· 数据模型不同（文本 vs 结构化）<br>· 无共享标识（`plans.id` 与 `trips.id` 无关联字段）<br>· 坐标来源不同（LLM 猜 vs OSM 真实）<br>· `/trip` 需登录，`/recommend` 免登录 | — |
| **依赖 localStorage** | **重度依赖 6 个键**：`yedu_plan`、`yedu_selected_spots`、`yedu_spot_coords`、`yedu_user_params`、`yedu_to_city`、`yedu_session_id` | 仅 `yedu_auth_token`（登录态）；行程数据全在 SQLite |
| **已进入 SQLite** | `plans` 表（78 行）：标题/城市/天数/预算/风格/身份/日期/spots(JSON 文本)/recommendation/plan_text/params | `trips`(7)/`trip_days`(18)/`trip_places`(13)：**含真实经纬度** |
| **需要大模型重新生成** | 景点推荐、攻略全文、**全部价格与费用明细**、坐标 | ❌ 不需要。地点来自 OSM，照片来自图源，均为真实数据 |
| **已是可计算、可编辑的结构化内容** | ❌ 无。费用明细只存在于 markdown 文本里，**无法计算、无法编辑** | ✅ `trip_places` 是结构化且可编辑的（拖拽换天已实现），**但目前没有任何费用字段** |

### 5.4 两套流程的关键结论

1. **两条链路在数据层完全隔离**，`/trip` 无法消费 `/recommend` 的景点推荐，反之亦然。
2. **真实数据只存在于 `/trip` 链路**（OSM 地点 + 图源照片）；`/recommend` 链路中除天气外，
   景点清单、门票价格、时长、餐饮店名、人均价、每日费用明细、坐标 **全部由模型生成**。
3. **唯一具备"可计算"潜力的数据结构是 `trip_places`**，但它当前**没有费用相关字段**
   （字段清单：`name, lat, lon, address, kind, source, source_url, sort_order, start_time, duration_min, note`）。
4. **`plans` 表把整篇攻略存成一个 `plan_text` 文本字段**，因此历史攻略无法被结构化利用。

---

## 六、当前最影响低预算旅行产品改造的五个问题（按严重程度排序）

### 问题 1（最高）：景点图片在前端**必然 404**——相对 URL 未补 API 基址

**严重度：高｜可复现性：100%｜影响：所有景点配图**

| 项 | 内容 |
|---|---|
| 现象 | 浏览器请求 `http://localhost:3000/api/images/<hash>.jpg` → **全部 404**（实测 9/9 失败） |
| 根因 | `frontend/src/lib/api.ts:1` 定义了 `API_BASE`，但**只用于 API 请求**；<br>`frontend/src/app/recommend/page.tsx:200` 把后端返回的**相对路径** `/api/images/…` 直接存为 `spot.image`；<br>`recommend/page.tsx:736` 直接 `<img src={spot.image}>` → 浏览器按**页面源**解析 |
| 佐证 | `next.config.ts` **无 rewrites/proxy**；全项目**没有一处**给图片 URL 补 `API_BASE` |
| 影响面 | 本地开发（3000 vs 8000）**以及线上**（CF Pages 前端 + HF Space 后端，**本就不同源**）→ 该功能在部署拓扑下**从未真正可用** |
| 备注 | 我曾误判为「不可复现」，因为我的探针**手动加了 `http://localhost:8000` 前缀**，正好绕过了缺陷。改用浏览器原生行为后 100% 复现 |

### 问题 2（高）：费用明细表**不渲染成表格**——缺少 `remark-gfm`

**严重度：高（对"预算规划"定位尤其致命）｜可复现性：100%**

| 项 | 内容 |
|---|---|
| 现象 | 真实攻略含 **6 个 markdown 表格**（门票预约总览表、每日费用明细），页面 `<table>` 数量为 **0** |
| 根因 | `frontend/src/app/plan/page.tsx:418` 使用裸 `<ReactMarkdown>{plan}</ReactMarkdown>`；`package.json` 中**无 `remark-gfm`** → GFM 表格语法不被解析 |
| 后果 | 用户看到的是**一屏带 `\|` 竖线的纯文本**。对低预算产品而言，"每天花多少钱"必须一眼可读 |
| 数据佐证 | 夹具中 120 行有 50 行含 `\|`、6 行是表格分隔行；渲染后 `<table>=0` |

### 问题 3（高）：高德地图链路已失效，`/plan` 地图降级为错误态

**严重度：高｜状态：后端 key 已确认回收；前端 key 无法在服务端验证**

| 项 | 内容 |
|---|---|
| 实测 | 高德 Web 服务接口返回 `status=0 / info=USER_KEY_RECYCLED / infocode=10013`；`/api/geocode` 因此恒返回 `lng:0, lat:0` |
| 前端实测 | AMap SDK 脚本已注入，但 **`window.AMap === false`**、无地图容器、页面显示「地图加载失败」 |
| 代码位置 | `backend/config.py:48`（`AMAP_WEB_KEY`）、`backend/main.py:632-666`（`/api/geocode`）、`frontend/src/components/RouteMap.tsx:25` |
| 对比 | **Leaflet 新地图工作正常**（1096×420px、15 张瓦片全 200）→ 说明问题只在旧高德链路 |
| 未验证项 | 前端 JS key 是否有效**需真实浏览器 + 有效 key 才能确认**，本次只能确认它加载失败 |

### 问题 4（中高）：密钥硬编码并已进入 git 历史

**严重度：中高（安全）**

| 项 | 内容 |
|---|---|
| 事实 | `backend/config.py` 已提交版本含 **5 个**硬编码默认值（`ZHIPU_API_KEY`/`ZHIPU_BASE_URL`/`CHAT_MODEL`/`UNSPLASH_ACCESS_KEY`/`AMAP_WEB_KEY`）；根 `config.py` 含 **4 个**（另有 `ARK_API_KEY`） |
| 另 | `frontend/.env.production` **已被 git 跟踪**，含高德 JS key 与安全密钥 |
| 对比 | `JWT_SECRET` 处理正确（环境变量 → 本地文件 → 随机，且 `backend/.jwt_secret` 已忽略）；`backend/.env` 与 `frontend/.env.local` 也正确忽略 |
| 风险 | 密钥随仓库分发；高德 key 已回收，与"公开暴露致回收"的因果**为推断而非实测** |

### 问题 5（中）：坐标与身份字段存在**错误数据 + 新旧不一致**

**严重度：中｜已在库中确认**

| 子问题 | 证据 |
|---|---|
| **坐标由 LLM 生成** | `backend/tools/images.py:635 geocode_spots()` 用大模型"猜"经纬度；实测 3 个景点耗时 **86.5 秒**，且 大昭寺 给 `91.1648` 而真实值 `91.1318`（**偏约 3 公里**） |
| **错误坐标已落库** | `trip_places` 中 `大昭寺 (43.998108, 143.749262)` = **日本北海道**（早期未做离群过滤时写入） |
| **`user_type` 新旧取值不一致** | `plans` 表 **78 行全部为 `'🎒 学生'`（含 emoji）**；而 P0 已把前端选项改为 `'学生'` → 同一列将出现两种取值。**提示词按"学生"匹配优惠规则**，因此历史数据可能静默不享受优惠 |
| 备注 | 该不一致是 **P0 去 emoji 的副作用**，属于下一阶段必须先决策的依赖项 |

### 其他已实测但严重度较低的问题

| 问题 | 证据 |
|---|---|
| 登录页文案过期 | 页面显示 **"Powered by LangChain + Qwen"**，实际模型已是智谱 GLM（`config.py:31`） |
| 限流会打断正常使用 | 登录 5 次/分、全局 API 30 次/60 秒，**按 IP 内存级**（`rate_limiter.py:34/37`）。测试中已实际触发 429 并导致登录失败 |
| 历史攻略大量重复 | `plans` 78 行中 `travel_type` 仅 3 种取值；存在 2 组完全重复的 `plan_text` → 早期"每轮修改新增一条"缺陷的历史遗留 |
| 会话状态在内存 | `main.py:274 sessions = {}`：多 worker/重启即丢（HF 免费档单 worker 才能工作） |
| 依赖清单含死包 | `langchain_openai` 无人引用；`langgraph` 仅被**线上不执行的** `agent.py` 引用 |
| **打开的行程不会被记住** | `frontend/src/app/trip/page.tsx` 中 **`localStorage` 出现 0 次**、无 URL 参数（无 `useSearchParams`/`router.push`）、无"上次行程 id"逻辑 → **刷新页面即回到"未打开任何行程"**。数据在 SQLite 中完好，但用户每次刷新都要重新点开行程 |
| 限流阈值与真实使用量接近 | 补测一轮内产生 **27 次 API 调用**（POI 搜索会为每张结果卡片各拉一次照片），上限是 **30 次/60 秒** → 单个用户连续操作即可能触顶 |

---

## 七、可直接复用的核心模块

### 7.1 实测已验证可用（可直接作为改造地基）

| 模块 | 路径 | 实测证据 | 复用价值 |
|---|---|---|---|
| **真实地点层** | `backend/tools/poi.py`（266 行） | 免 key；含 300km 离群过滤；库中 `trip_places.source` 全为 `openstreetmap` | **低预算产品的"真实景点"基座** |
| **地点照片层** | `backend/tools/photos.py`（244 行） | 缩略图压缩（174–479KB → 26–72KB）、10 秒总截止、图床黑名单、查询链带城市 | 图片体验的现成实现（**需配合问题 1 修复才可见**） |
| **攻略搜索层** | `backend/tools/websearch.py`（143 行） | Tavily 公开结果 + 来源分类 | 后续"真实攻略参考"入口 |
| **结构化行程 CRUD** | `backend/trips.py`（282 行） | `/api/trips` 实测 200；含跨天拖拽与越权保护 | **唯一可承载"可计算预算"的数据结构** |
| **天气** | `backend/tools/search.py`（42 行） | wttr.in 免 key，已在 `/recommend` 与 `/generate-plan` 注入 | 真实数据的低成本样板 |
| **Word 导出** | `backend/tools/export.py`（302 行） | 实测导出 42KB `.docx` | 成品级导出 |
| **AI 生成闭环** | `backend/main.py:401/423/468/543` | 实测：推荐 ✅、生成 ✅、修改 ✅（5614→5900 字） | 产品骨架 |
| **Leaflet 地图组件** | `frontend/src/app/trip/page.tsx`（MapPanel） | 实测 1096×420px、15 瓦片全 200、三底图可切、GCJ-02 纠偏 | **可替代失效的高德链路** |
| **设计 token** | `frontend/src/app/globals.css` | 实测底色 `rgb(250,248,244)`、标题衬线字体生效、蓝色元素 0 | 视觉一致性基础 |
| **UI 基座** | `frontend/src/components/ui/`（8 个文件） | 已用于首页/推荐页/攻略页 | 后续页面统一 |
| **共享头部** | `frontend/src/components/SiteHeader.tsx` | 已用于首页与内页 | 导航统一 |
| **鉴权与密钥管理** | `backend/auth.py`、`config.py:40+` | 经 UI 登录实测 200 + `yedu_auth_token` 落盘；JWT 密钥处理正确 | 用户体系（Demo 阶段可不用，但可用） |
| **回归脚本** | `ops/verify_poi.py`(14)、`verify_place_photos.py`(8)、`verify_trips.py`(10) | 均有明确断言与 `check()` 结构 | 改造安全网 |

### 7.2 明确的技术债（复用前需先处理）

| 债项 | 路径 | 说明 |
|---|---|---|
| 死代码：LangGraph Agent | `backend/agent.py`（154 行） | 仅被根目录遗留 `app.py` 引用；3 个"工具"是空壳；线上 `main.py` 完全不 import |
| 遗留 Streamlit 应用 | 根 `app.py`（762 行） | 依赖 `streamlit`，但 `requirements.txt` 无此依赖 → 容器内跑不起来 |
| 过期文档 | `PRD.py`、`笔记.py` | PRD 写 Streamlit+LangGraph+Qwen；笔记写"通义万相"，均与现状不符 |
| 正则解析模型输出 | `backend/tools/images.py:495/543` | 全站 UI 依赖模型严守 emoji+markdown 格式，无校验无重试 |
| LLM 猜坐标 | `backend/tools/images.py:635` | 既不真实又慢（86.5s/3 点） |
| 巨石文件 | `main.py` 1054 / `trip/page.tsx` 1003 / `recommend/page.tsx` 969 | 无组件化拆分 |
| 两套图片通道 | `/api/spot-images`（Pixabay 自托管）与 `/api/poi/photos`（Tavily） | 版权口径与体验不一致 |

---

## 八、下一阶段建议处理的技术依赖与前置条件

> 按依赖关系排序。**这些是"要不要做/先做哪个"的决策输入，不是改造方案。**

### 8.1 必须先决策（阻塞后续所有工作）

| # | 前置条件 | 为什么阻塞 |
|---|---|---|
| 1 | **为未提交的约 2,400 行建立版本保护**（提交或建分支） | 当前 POI/照片/搜索/行程四个模块、`/trip` 页、9 个 UI 组件**只在本机磁盘**。任何清理/换机操作即永久丢失 |
| 2 | **确认 `plans.user_type` 新旧取值口径**（历史 78 行为 `'🎒 学生'`，P0 后新数据为 `'学生'`） | 提示词按「学生」匹配优惠规则 → **历史数据可能静默不生效**。需决定：迁移旧值、或写兼容匹配、或保留双写 |
| 3 | **确认坐标策略**（LLM 猜 vs OSM 真实） | `/recommend` 链路坐标偏 ~3km 且 86.5s/3 点；`/trip` 链路坐标真实。**做低预算规划必须用可信坐标**，否则距离/交通成本无从计算 |
| 4 | **决定高德链路的去留** | 后端 key 已回收、前端地图降级报错。Leaflet 方案实测可用（免 key）→ 需明确"修高德"还是"全面切 Leaflet" |

### 8.2 影响体验与验证效率，建议尽早处理

| # | 前置条件 | 证据 |
|---|---|---|
| 5 | 修复**景点图片 404**（前端补 API 基址或加代理） | 实测 9/9 失败；且线上拓扑同样受影响 |
| 6 | 启用 **`remark-gfm`** 让 markdown 表格渲染为真表格 | 真实输出含 6 个表格，当前全部退化为纯文本 |
| 7 | 统一 dev 访问方式（`localhost`）或配置 `allowedDevOrigins` | 用 `127.0.0.1` 会静默不 hydration，**极易被误判为产品故障**（本次已误判一次） |
| 8 | 复核**限流阈值**与测试节奏 | 登录 5 次/分、全局 API 30 次/分（按 IP 内存级）→ 自动化测试与真实使用都可能被 429 打断（已实际发生） |
| 9 | 处理**硬编码密钥**（源码兜底值 + 被跟踪的 `.env.production`） | 已进入 git 历史，需评估是否轮换 |
| 10 | 让 `/trip` 记住"当前打开的行程"（URL 参数或 localStorage 存 trip id） | 实测刷新后视图清空、需重新点开（数据在 SQLite 中未丢）；`trip/page.tsx` 中 `localStorage` 出现 0 次 |

### 8.3 低预算能力的前置条件（本阶段不作为，仅登记依赖）

| 能力 | 当前缺口 | 已有可复用部分 |
|---|---|---|
| 费用估算 | **无任何价格数据源**；`tools/` 下无价格查询代码；费用仅为模型估算文本 | `tools/export.py`（结构化后可直接排版导出） |
| 费用可计算 | `plans.plan_text` 是大文本；`trip_places` **无费用字段** | `trips` 三表结构可扩展 |
| 交通比价 | 交通只是 4 个硬编码偏好选项 | 表单与参数链路已通 |
| 多城市联游 | `to_city` 全程单值 | `trips` 表结构可容纳 |
| 学生优惠 | 仅提示词里的硬编码折扣规则，**无数据源、无校验** | 用户身份 5 个选项 + 提示词规则 |
| 真实价格 | 唯一实时数据是天气 | 无 |

### 8.4 建议的验证节奏

1. 每次改动后跑既有回归：`ops/verify_poi.py`(14) / `verify_place_photos.py`(8) / `verify_trips.py`(10)
2. 浏览器端回归必须用 **`http://localhost:3000`**，并在断言中加入
   「可交互元素是否有 React fiber」这一项，防止再次把环境问题误判为产品缺陷
3. 断言中加入**图片请求状态码**与**`<table>` 数量**，以覆盖问题 1 与问题 2

---

## 附录 A：本报告的未验证项（明确登记，不写作通过）

| 项 | 未验证原因 |
|---|---|
| 前端高德 JS key 是否有效 | 需真实浏览器 + 有效 key 才能判定；本次仅确认 SDK 加载后 `window.AMap` 未就绪 |
| 景点坐标是否存在 (0,0) | `/recommend → /plan` 链路本次未取到坐标样本（生成流程采样过早），未取得该链路的样本 |
| 线上 HF Space 与 CF Pages 端到端 | 本报告仅覆盖**本地环境** |
| 跨浏览器兼容性 | 仅测试 Chromium（Playwright 内置） |
| 移动端完整交互流程 | 仅测了首页移动布局，未在移动视口执行完整流程 |
| 分享按钮的完整调用链 | 未逐行确认 |

### 附录 B：补充验证轮（第二轮，关闭了首轮的 C 组未验证项）

首轮 C 组的 4 项未验证**根因是测试脚本缺陷**（未先打开行程 → POI 搜索框未渲染）。第二轮针对性补测后：

| 首轮状态 | 第二轮结论 | 证据 |
|---|---|---|
| ⬜ `/trip` 搜索并加入地点 | ✅ **通过** | 打开「拉萨行程 3 个地点」→ 搜「大昭寺」→ 2 个「加入」按钮 → Day1 地点数 **3 → 4** |
| ⬜ 跨天拖拽地点 | ✅ **通过** | HTML5 拖拽事件后布达拉宫 **Day1 → Day2**，总数保持 4；**库中 `day_index = 1` 已落盘** |
| ⬜ 刷新后数据仍在 | ✅ **数据通过** / ❌ **视图不恢复** | 库侧 trip 6 = 4 个地点（Day1 3 + Day2 1）；但页面刷新后不再自动打开该行程 |
| ⬜ 坐标质量 | ✅ **真实坐标通过** / ❌ **历史脏数据仍在** | 新增地点全部 `source=openstreetmap` 且坐标正确；但 trip 6 中仍存有 `大昭寺 (43.998108, 143.749262)`（日本） |

**补充轮额外确认的两点**：

1. **300km 离群过滤按设计工作**：用拉萨行程搜成都的「宽窄巷子」被正确挡掉（0 结果），换搜同城「大昭寺」正常返回。
2. **景点图片 404 缺陷再次复现 4 次**（`http://localhost:3000/api/images/…`），进一步佐证 §6 问题 1。