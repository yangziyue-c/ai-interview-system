# AI 模拟面试与能力提升系统

面向计算机专业学生的 AI 模拟面试训练系统，覆盖 **后端开发工程师**、**前端开发工程师**、
**测试开发工程师** 三个岗位：

- 🤖 **岗位化面试对话**：题库策略出题（题库 V4 已入库 451 题）——开场热身/核心考察/深度考察/
  收尾交流四阶段 + 追问触发条件（L1 关键词 → L2 递进 → L3 极限 → 降级策略）动态追问，支持语音/文本
- 📊 **五维评估报告**：技术水平、逻辑思维、沟通表达、应变能力、岗位匹配度
- 📈 **能力成长曲线**：历史面试得分趋势可视化

> 仓库地址：https://github.com/yangziyue-c/ai-interview-system

## 技术栈

| 层 | 技术 |
| :--- | :--- |
| Web 框架 | Python FastAPI（异步） |
| ORM | SQLAlchemy 2.0（异步） |
| 数据库 | MySQL（默认开发环境用 SQLite 零配置启动，`.env` 一键切换） |
| 缓存 | Redis（未配置时自动降级为进程内缓存） |
| 鉴权 | JWT（PyJWT + bcrypt） |
| 前端 | 独立仓库目录，构建产物由后端挂载（同端口，无跨域） |

## 目录结构

```
project/
├── backend/                  # 后端（P1 负责）
│   ├── app/
│   │   ├── main.py           # FastAPI 入口（CORS *、静态挂载、全局异常处理）
│   │   ├── config.py         # 配置（读取 .env）
│   │   ├── database.py       # SQLAlchemy 异步引擎
│   │   ├── redis_client.py   # Redis/内存缓存双实现
│   │   ├── core/             # 异常体系、JWT 鉴权、面试状态机、评估权重
│   │   ├── models/           # 用户/面试/问答/报告/岗位/题库 六张表（含受控词表常量）
│   │   ├── schemas/          # Pydantic 请求响应模型
│   │   ├── adapters/         # 出题/评估适配器（数据源链 + 超时降级）
│   │   ├── api/              # 认证/面试/报告/题库/上传 路由
│   │   └── utils/            # 统一响应格式
│   ├── interviewer/          # 面试官出题算法（P2，已原生落地，题库策略）
│   ├── evaluator/            # 评估服务（P3，独立 Flask 进程，端口 8002）
│   ├── scripts/              # 题库导入脚本（import_question_bank.py）
│   ├── static/               # 前端 dist 挂载目录（P4 构建产物放这里）
│   ├── uploads/              # 面试录音文件
│   ├── tests/                # 全流程回归测试（60 用例）
│   ├── requirements.txt
│   ├── .env.example          # 环境变量模板
│   └── start.bat             # Windows 一键启动（自动拉起演示前端 + P3 + 主后端）
├── frontend/                 # 正式前端（P4 负责，构建产物拷 backend/static/）
├── frontend_test/            # 演示前端（P1，零依赖纯 HTML/JS，start.bat 自动拉起到 5273）
├── 题库/                      # 岗位化面试题库 xlsx V4（P5 整理，scripts 导入 questions 表）
├── docs/
│   ├── API.md                # 接口文档（唯一权威）
│   ├── DATABASE.md           # 数据库设计文档
│   ├── DEPLOY.md             # 内网穿透部署说明
│   ├── COLLABORATION.md      # Git 协作指南
│   └── reports/              # 各成员对接文档 REPORT_TO_P2~P5
└── 评估维度.csv               # 五维评分权重定稿（机器校验与代码一致）
```

## 快速开始（Windows）

**方式一：一键启动（推荐）**

双击 `backend/start.bat`：
1. 自动检测/创建 conda 环境 `ai_interview`（Python 3.12）
2. 自动安装依赖（清华镜像源）
3. 自动生成 `.env`
4. 启动演示前端（frontend_test/ → **5273 端口**）+ P3 评估服务（8002）+ 主后端（8001）
5. 服务就绪后打印**访问指引**（本机 + 局域网地址与各自用途）；Ctrl+C 一并退出三个服务

> 演示前端端口 5273 特意避开了 5173（P4 联调用的 Vite dev 端口），两边互不冲突。

**方式二：手动启动**

```bat
conda create -n ai_interview python=3.12 -y
conda activate ai_interview
cd backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

启动后（端口约定：8000 被本机 Godot AI MCP 占用，勿改回）：

| 地址 | 说明 |
| :--- | :--- |
| http://localhost:5273 | **演示前端**：注册登录 / 模拟面试 / 评估报告 / 个人中心 |
| http://localhost:8001/docs | Swagger 接口文档（可直接在线调试） |
| http://localhost:8001/api/v1/health | 健康检查 |
| http://localhost:8001 | 正式前端（P4 构建产物放入 `backend/static/` 后同端口访问） |

### 故障排查：双击 start.bat 报乱码或「xxx 不是内部或外部命令」

这是文件行尾损坏导致的（cmd 要求 CRLF 行尾）。在 `backend` 目录打开 PowerShell，执行：

```powershell
$c = [IO.File]::ReadAllText('start.bat')
$c = $c -replace "`r?`n", "`r`n"
[IO.File]::WriteAllText('start.bat', $c, (New-Object Text.UTF8Encoding($false)))
```

然后重新双击 start.bat。若问题依旧，请到 GitHub 清除浏览器缓存后重新下载仓库 zip（旧 zip 可能被浏览器/下载器缓存）。

## 切换数据库与缓存

编辑 `backend/.env`：

```ini
# 默认 SQLite（零配置，演示/开发推荐）
DATABASE_URL=sqlite+aiosqlite:///./interview.db

# 切换 MySQL（先在 MySQL 中执行建库）：
#   CREATE DATABASE interview_db DEFAULT CHARACTER SET utf8mb4;
# DATABASE_URL=mysql+aiomysql://root:你的密码@127.0.0.1:3306/interview_db

# Redis：留空 = 进程内缓存；配置后自动启用
# REDIS_URL=redis://127.0.0.1:6379/0
```

## 核心设计

### 面试状态机

```
idle → in_progress → finished（终态）
```

- 开始面试：生成开场题（第 1 轮）
- 提交答案：保存 → 未达上限生成追问 → 达上限自动结束并出报告
- 轮次上限 = 1 道开场题 + `MAX_FOLLOW_UP_ROUNDS`（默认 6）轮追问，共 7 题
- 非法状态操作统一返回 `409`

### 统一响应格式

```json
{ "code": 0, "message": "ok", "data": { } }
```

错误码：`0` 成功；`400xx` 参数错误；`401xx` 未认证；`403xx` 无权限；`404xx` 不存在；`409xx` 状态冲突；`500xx` 内部错误。全局异常兜底，任何异常都不会返回非统一格式的响应。

### 面试出题：题库策略优先（backend/interviewer/）

出题数据源链（每级失败自动降级，流程永不中断）：

```
题库策略（questions 表 451 题）> AI_INTERVIEWER_URL（外部服务扩展位）> LLM 直连 > 内置 Mock
```

- P2 的面试官算法已**原生落地**在 `backend/interviewer/question_bank.py`：
  开场热身/核心考察/深度考察/收尾交流四阶段选题 + 追问锚点层级推断（L1→L2→L3→降级）；
- `AI_INTERVIEWER_URL`（外部服务）/ `LLM_API_KEY`（大模型直连）仅为题库未命中时的兜底；
- 评估侧 `AI_EVALUATOR_URL` 指向 P3 服务（start.py 自动拉起 8002 端口），失败降级 Mock 评分。

### 面试流程规则

- 每场 7 轮 = 1 开场题（开场热身 + easy）+ 6 追问（`MAX_FOLLOW_UP_ROUNDS`，config.py 可调）
- **最后两轮强制收尾交流**（round 6/7）——真实题库每题都带追问计划，不强制则收尾题永不出现
- 非法状态操作统一返回 `409`

### 五维评分权重

技术/逻辑/表达/应变/匹配五维按岗位加权，权重单一事实源 `backend/app/core/evaluation_weights.py`
（与根目录《评估维度.csv》机器校验一致）。

## 运行测试

```bash
cd backend
D:/anaconda3/envs/ai_interview/python.exe -m pytest    # 60 个用例全绿（测试库 test_interview.db，不污染开发库）
```

> 本机 `conda run` 有插件 bug，请直接调用 ai_interview 环境内的 python.exe
> （环境真实位置用 `conda env list` 查询）。测试**必须在 backend/ 目录下运行**
> （pytest.ini 的 asyncio 配置与 conftest 的环境切换依赖该目录）。

## 内网穿透演示

手机/外网访问本机服务，详见 [docs/DEPLOY.md](docs/DEPLOY.md)（Sakura Frp / NatApp 两种方案）。

## 团队成员分工

| 角色 | 人数 | 职责 |
| :--- | :---: | :--- |
| P1 后端开发A（兼技术负责人） | 1人 | 主后端 `backend/app/`：数据库设计、面试流程状态机、对话管理API、题库导入/查询接口、适配器集成、部署运维、进度把控、功能测试与文档 |
| P2 后端开发B（AI专项1） | 1人 | 面试官出题算法 `backend/interviewer/`：题库策略（开场/追问/收尾选题、追问触发 L1→L2→L3→降级） |
| P3 后端开发C（AI专项2） | 1人 | 评估服务 `backend/evaluator/`：内容多维度判分、五维报告生成、改进建议生成 |
| P4 前端开发（Web端） | 1人 | 页面：注册登录、岗位大厅、面试对话室（语音录制/Web Speech 转写）、五维雷达图报告/成长曲线 |
| P5 知识库构建  | 1人 | 整理各岗位面试题库 xlsx（V4，含参考答案/难度/得分点/追问触发条件）、知识点库 |
