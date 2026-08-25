# AI 模拟面试与能力提升系统

面向计算机专业学生的 AI 模拟面试训练系统，覆盖 **后端开发工程师** 与 **前端开发工程师** 两个岗位：

- 🤖 **多模态面试对话**：AI 面试官根据岗位出题、动态追问（语音/文本）
- 📊 **多维度评估报告**：技术、逻辑、表达、岗位匹配度四个维度
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
│   │   ├── models/           # 用户/面试/问答/报告 四张表
│   │   ├── schemas/          # Pydantic 请求响应模型
│   │   ├── adapters/         # P2/P3 适配器（Mock + 15 秒超时降级）
│   │   ├── api/              # 认证/面试/报告/上传 路由
│   │   └── utils/            # 统一响应格式
│   ├── static/               # 前端 dist 挂载目录（P4 构建产物放这里）
│   ├── uploads/              # 面试录音文件
│   ├── tests/                # 全流程回归测试（P5 验收参考）
│   ├── requirements.txt
│   ├── .env.example          # 环境变量模板
│   └── start.bat             # Windows 一键启动
├── frontend/                 # 前端（P4 负责）
├── docs/
│   ├── API.md                # 接口文档
│   ├── DEPLOY.md             # 内网穿透部署说明
│   └── COLLABORATION.md      # Git 协作与权限授予
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
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后：

| 地址 | 说明 |
| :--- | :--- |
| http://localhost:8000/docs | Swagger 接口文档（可直接在线调试） |
| http://localhost:8000/api/v1/health | 健康检查 |
| http://localhost:8000 | 前端页面（构建产物放入 `backend/static/` 后） |

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

| 角色 | 职责 |
| :--- | :--- |
| P1 | 后端架构、数据库设计、核心 API、部署运维 |
| P2 | AI 对话（大模型、RAG、Prompt、追问生成） |
| P3 | AI 评估（语音识别、多维度评分、报告生成） |
| P4 | 前端（Web 界面、语音录制、报告可视化） |
| P5 | 数据与测试（题库、测试用例、全流程回归） |
