# 前端连接后端指南（联调与部署）

> **面向**：前端（4 号）
> **本文只讲怎么把前端接到后端上**。接口路径与字段以 [API.md](API.md) 为唯一权威，
> 页面需求见 [REPORT_TO_P4.md](reports/REPORT_TO_P4.md)。

---

## 一、结论

两种接法，按阶段选一种：

| | 前端跑在哪 | 怎么访问后端 | 用在哪 |
| :--- | :--- | :--- | :--- |
| 开发联调 | Vite dev server，端口 5173 | 直连 `http://localhost:8001/api/v1` | 日常开发 |
| 部署演示 | 构建产物放后端静态目录 | 与 API 同端口，相对路径 `/api/v1` | 交付、演示、穿透 |

后端 CORS 配置为通配符 `*`，**两种接法都不需要配 Vite 代理**。

---

## 二、端口清单

| 端口 | 服务 | 谁拉起 |
| :--- | :--- | :--- |
| 8001 | 主后端（API + 部署后的前端页面） | `start.bat` |
| 8002 | P3 评估服务 | `start.bat` 自动 |
| 8003 | RAG 语义检索 | `start.bat` 自动 |
| 8005 | AI 对话层引擎（可选，见第五节第 3 条） | `start.bat` 自动 |
| 5173 | 你的 Vite dev server | 你自己 |
| 5273 | P1 的演示前端 `frontend_test/` | `start.bat` 自动 |

8001 是全组统一端口（8000 被本机其他程序占用），不要改成 8000。

---

## 三、开发联调（模式 A）

### 1. 起后端

```bash
cd backend
双击 start.bat
```

或者不用 `start.bat`、只起主服务：

```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

两条命令都**必须在 `backend/` 目录下执行**。`STATIC_DIR` 与 `UPLOAD_DIR` 都是相对路径
（[config.py:114](../backend/app/config.py#L114) 的 `STATIC_DIR = "static"`），换个目录启动会把
静态目录与上传目录建到别处，表现是页面打不开、上传的文件找不到。

首次启动前需要 `backend/.env`。`start.bat` 会自动生成，手动起 uvicorn 的要自己来一份：

```bash
cd backend && cp .env.example .env
```

这不是可选项：`.env` 缺失时评估服务地址为空串，适配器会**静默走内置 Mock**，
所有报告都返回模板化的分数与评语。联调时看到「每个人的报告都差不多」多半就是这个原因。

起好后打开 `http://localhost:8001/docs` 确认 Swagger 能出，再往下走。

### 2. 配 Base URL

```js
const API_BASE = import.meta.env.DEV
  ? "http://localhost:8001/api/v1"    // 联调：与后端同机
  : "/api/v1";                         // 部署：与 API 同端口，走相对路径
```

用手机或另一台机器访问你的 dev server 联调时，把 `localhost` 换成你机器的局域网 IP
（后端监听 `0.0.0.0`，局域网可直连）。

### 3. 带 token

除了注册与登录，所有接口都要 `Authorization: Bearer <token>`。统一响应格式是
`{ "code": 0, "message": "ok", "data": ... }`，`code !== 0` 即失败；`40100` 表示登录失效，
清掉本地 token 跳登录页即可。

---

## 四、部署演示（模式 B）

```bash
npm run build
# 把 dist/ 下的全部内容拷进 backend/static/，覆盖那里的占位 index.html
```

后端启动时把根路径挂成静态目录（[main.py:93](../backend/app/main.py#L93)）：

```python
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
```

挂载顺序是 API 路由 → `/uploads` → `/` 兜底，所以 `/api/v1/*` 不会被静态目录截走。
访问 `http://localhost:8001` 就是前端页面，与接口同源，没有跨域这回事。

两个注意点：

- **拷完要重启后端**，静态目录是启动时挂载的；
- 这份静态挂载**没有 SPA fallback**，理由见下一节第 1 条。

---

## 五、三条硬约束

### 1. 路由用 hash 模式

`StaticFiles` 只会按路径找文件，找不到就 404，**不会回落到 `index.html`**。
如果前端用 Vue Router 的 history 模式，从首页点进去正常，但**刷新任意子路径、或直接打开深链
都会 404**。

后端生成的分享链接是 hash 形式（`https://<host>/#/share/<code>`，见
[report.py:65](../backend/app/schemas/report.py#L65)），前端路由模式要对得上。

### 2. Base URL 不要写死 `localhost`

写死之后，局域网访问、内网穿透（见 [DEPLOY.md](DEPLOY.md)）都会失败，因为 `localhost`
指向访问者自己的机器。部署形态下用相对路径 `/api/v1`，前端跑到哪都跟着走。

### 3. 引擎模式下请求超时不能设短

后端可以用 `backend/.env` 的 `DIALOGUE_ENGINE=a11` 切到 AI 对话层引擎（10 题制）。该模式下：

- 提交答案的请求超时 **≥540 秒**，结束面试 **≥360 秒**；
- 对话层在外部大模型偶发卡住时不返 5xx，而是把超时预算跑完再收尾。前端自己掐断会让
  正常场次失败，而后端日志里看不出异常；
- 依赖未就绪时接口返回 **503（错误码 50300）**，按「服务暂时不可用，稍后重试」处理，
  不要和 500 合并。

默认配置（`DIALOGUE_ENGINE` 留空）不受这条影响。判断当前是哪条链路用 `GET /config`
的 `engine` 字段。

---

## 六、常见问题

| 现象 | 原因 | 处理 |
| :--- | :--- | :--- |
| 刷新子路径 404 | history 路由 | 改成 hash 模式 |
| 打开 `:8001` 是占位页 | 构建产物没拷 | 把 `dist/` 内容拷进 `backend/static/` 后重启 |
| 接口全部 404，但 Swagger 正常 | Base URL 少了 `/api/v1` | 补成 `.../api/v1` |
| CORS 报错 | 访问了旧地址或旧端口 | 后端已开 `*`，确认请求打的是 8001 |
| 40100 | token 过期或没带 | 清 token 跳登录页 |
| 报告分数与评语千篇一律 | 后端缺 `.env`，走了 Mock 兜底 | 检查 `backend/.env`，见第三节第 1 条 |
| 409 冲突 | 已有进行中的面试，或面试尚未结束就想看报告 | 见 [REPORT_TO_P4_FEATURE_CHECK.md](reports/REPORT_TO_P4_FEATURE_CHECK.md) 第六节的边界表 |
| 上传大文件失败 | 超过体积上限 | 录音与头像各有上限，见 [API.md](API.md) 第 6 节 |

---

## 七、语音这块可以用的接口

你的清单里写的是浏览器端 Vosk 离线识别。后端另外提供两个接口，按需选用：

- `POST /uploads/audio`：只保存文件，返回 `url`，转写自己做；
- `POST /uploads/audio/asr`：**转写与保存一次完成**，同时返回文本与 `url`，同一个文件不用传两次。
  转写用后端本地的 faster-whisper 模型，未就绪时返回 503，不要当空文本处理。

用哪个由你定，两者不冲突。

---

## 八、联调自检

开工前 `git pull`，然后对照 [API.md](API.md) 逐条核对每个请求的方法、路径、请求体字段与
响应字段。字段差异清单见 [REPORT_TO_P4_FEATURE_CHECK.md](reports/REPORT_TO_P4_FEATURE_CHECK.md)，
页面需求见 [REPORT_TO_P4.md](reports/REPORT_TO_P4.md)。
