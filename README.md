# AI 模拟面试与能力提升系统

面向计算机专业学生的 AI 模拟面试训练系统，覆盖 **后端开发工程师**、**前端开发工程师**、
**测试开发工程师** 三个岗位：

- 🤖 **岗位化面试对话**：面试官从题库（3 岗位 × 150 题）抽题、按追问触发条件动态追问（语音/文本）
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
│   │   ├── core/             # 异常体系、JWT 鉴权、面试状态机
│   │   ├── models/           # 用户/面试/问答/报告/岗位/题库 六张表
│   │   ├── schemas/          # Pydantic 请求响应模型
│   │   ├── adapters/         # P2/P3 适配器（Mock + 15 秒超时降级）
│   │   ├── api/              # 认证/面试/报告/题库/上传 路由
│   │   └── utils/            # 统一响应格式
│   ├── evaluator/            # 评估服务（P3，独立 Flask 进程，端口 8002）
│   └── scripts/              # 题库导入脚本（import_question_bank.py）
│   ├── static/               # 前端 dist 挂载目录（P4 构建产物放这里）
│   ├── uploads/              # 面试录音文件
│   ├── tests/                # 全流程回归测试（P5 验收参考）
│   ├── requirements.txt
│   ├── .env.example          # 环境变量模板
│   └── start.bat             # Windows 一键启动
├── frontend/                 # 前端（P4 负责）
├── 题库/                      # 岗位化面试题库 xlsx（P5 整理，scripts 导入 questions 表）
├── docs/
│   ├── API.md                # 接口文档
│   ├── DATABASE.md           # 数据库设计文档
│   ├── DEPLOY.md             # 内网穿透部署说明
│   └── COLLABORATION.md      # Git 协作指南
└── frontend/                 # 前端
```

## 快速开始（Windows）

**方式一：一键启动（推荐）**

双击 `backend/start.bat`：
1. 自动检测/创建 conda 环境 `ai_interview`（Python 3.12）
2. 自动安装依赖（清华镜像源）
3. 自动生成 `.env`
4. 启动服务

**方式二：手动启动**

```bat
conda create -n ai_interview python=3.12 -y
conda activate ai_interview
cd backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

启动后：

| 地址 | 说明 |
| :--- | :--- |
| http://localhost:8001/docs | Swagger 接口文档（可直接在线调试） |
| http://localhost:8001/api/v1/health | 健康检查 |
| http://localhost:8001 | 前端页面（构建产物放入 `backend/static/` 后） |

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

### P2/P3 适配器（Mock + 超时降级）

- `.env` 中 `AI_INTERVIEWER_URL` / `AI_EVALUATOR_URL` 留空 → 使用内置 Mock 题库与评分
- 填入地址 → 自动调用真实服务，**15 秒超时自动降级 Mock**，面试流程永不中断
- 接入约定详见 [backend/app/adapters/](backend/app/adapters/) 目录内注释与 [docs/API.md](docs/API.md)

## 运行测试

```bat
cd backend
conda activate ai_interview
pytest
```

测试使用独立 SQLite 库（`test_interview.db`），不污染开发数据。

## 内网穿透演示

手机/外网访问本机服务，详见 [docs/DEPLOY.md](docs/DEPLOY.md)（Sakura Frp / NatApp 两种方案）。

## 团队成员分工

| 角色 | 人数 | 职责 |
| :--- | :---: | :--- |
| 后端开发A（兼技术负责人） | 1人 | 数据库设计、面试流程状态机、对话管理API、用户历史记录、部署运维、进度把控 |
| 后端开发B（AI专项1） | 1人 | 对接大模型API，负责面试官对话逻辑（人设Prompt、追问生成、节奏控制）、RAG检索服务 |
| 后端开发C（AI专项2） | 1人 | 负责评估模块：内容多维度判分、表达分析API集成（ASR后处理）、综合报告生成、改进建议生成 |
| 前端开发（Web端） | 1人 | 负责语音录制/播放组件、文本聊天界面、流式对话展示、报告可视化页面（雷达图/成长曲线） |
| 知识库构建 + 测试/文档 | 1人 | 核心工作：整理各个岗位的面试题库（含参考答案、难度标签、考察维度）、知识点库，同时负责功能测试和提交文档 |
