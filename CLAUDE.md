# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CLAUDE.md — AI 模拟面试系统项目指令

## 项目总览与团队分工

AI 模拟面试训练系统（FastAPI 异步 + SQLAlchemy 2.0，5 人小组项目）：

| 成员 | 职责 | 代码/文档位置 |
| :--- | :--- | :--- |
| P1（本机） | 主后端 + 集成 | `backend/app/` |
| P2 | 面试官出题算法 | `backend/interviewer/question_bank.py`（已原生落地） |
| P3 | AI 评估服务 | `backend/evaluator/`（独立 Flask 进程，端口 8002） |
| P4 | 前端 | `frontend/`（构建产物拷 `backend/static/` 同端口挂载） |
| P5 | 题库 | `题库/*.xlsx`（V4 版）→ `questions` 表（见 `docs/reports/REPORT_TO_P5.md` 操作手册） |

对接文档在 `docs/reports/REPORT_TO_P2~P5.md`；接口唯一权威 `docs/API.md`。
**P2 修改算法只动 `backend/interviewer/`**（其 README 有算法速览与踩坑清单），
P3 只动 `backend/evaluator/`，P5 只产 `题库/*.xlsx`（导入命令见其对接文档）；
`backend/app/` 是集成层，别把成员代码塞进来。
P1 维护的零依赖**演示前端**在 `frontend_test/`（`start.bat` 自动拉起到 5273，P4 正式前端交付前的整体演示入口；与 P4 的 `frontend/` 互不相干、不抢 5173 联调端口）。

## 常用命令（conda 环境 ai_interview）

> `conda run` 有插件 bug，**直接调用环境内 python.exe**。本机实测路径
> `D:/anaconda3/envs/ai_interview/python.exe`，环境真实位置以 `conda env list` 为准。

```bash
# 一键启动：演示前端（5273，frontend_test/）+ P3 评估服务（8002）+ 主服务（8001），
# 就绪后打印访问指引（本机+局域网地址），Ctrl+C 一并退出
cd backend && 双击 start.bat        # 或 python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# 测试：必须在 backend/ 目录下跑（pytest.ini 的 asyncio_mode、conftest 的 env 切换都在这里生效）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m pytest        # 60 个用例全绿
D:/anaconda3/envs/ai_interview/python.exe -m pytest tests/test_question_bank.py -q   # 单文件
D:/anaconda3/envs/ai_interview/python.exe -m pytest tests/test_api.py::TestAuth::test_login_wrong_password  # 单用例

# 题库导入（题库/ 有新 xlsx 后重跑，幂等；注意必须用 -m，直接 python scripts/xxx.py 会因 sys.path 找不到 app 包）
cd backend && D:/anaconda3/envs/ai_interview/python.exe -m scripts.import_question_bank
```

- 测试库 `test_interview.db`：conftest 在 import 时自动删除重建并注入环境变量
  （DATABASE_URL 指向测试库、清空 LLM_API_KEY 防误调真实大模型）——**不会碰开发库 interview.db**
- 测试造数用共享工厂 `backend/tests/helpers.py` 的 `make_question()`（question_no 自动随机后缀防唯一约束冲突）

## 代码架构（大图）

**目录布局**：`backend/app/`（主应用包）+ `backend/interviewer/`、`backend/evaluator/`
（成员成果目录，主应用 import/拉起）。

### 面试出题：四级数据源链（app/adapters/ai_interviewer.py）

```
题库策略(interviewer/question_bank.py) > AI_INTERVIEWER_URL(外部服务扩展位) > LLM 直连 > 内置 Mock
```

- **题库策略是最高优先级**：查 questions 表（451 题：backend 151 + frontend 150 + test_engineer 150），
  岗位有题即走题库，外部服务/LLM 只在题库未命中时生效（勿按 .env.example 旧注释误判）
- 每级失败自动落下一级，流程永不中断；HTTP/LLM 级各 15 秒超时（串行时最坏叠加 ~30 秒到 Mock）
- SQLite 已配 **WAL + busy_timeout**（database.py 事件监听），并发写不会锁库；
  适配器题库查询自开只读短会话，**不要复用请求级会话传 db**（会触发 autoflush 提前锁库）
- 核心业务规则（question_bank.py）：1 开场题 + 6 追问共 7 轮（`MAX_FOLLOW_UP_ROUNDS=6`，config.py）；
  开场=开场热身+easy；**round 6/7 强制收尾交流**（不强制则真实题库的追问链延伸到最后一轮，收尾题永不出现——已实测验证）；追问按锚点+层级 L1→L2→L3→降级

### 评估与报告（P3 + 主后端兜底）

- `backend/evaluator/`（Flask 8002）由 start.py 自动拉起；主后端 `app/adapters/ai_evaluator.py`
  Mock 兜底，调用失败自动降级
- 报告 **5 维评分**（技术/逻辑/表达/应变/匹配），各岗位权重单一事实源 =
  `app/core/evaluation_weights.py` 的 `POSITION_CONFIG`（源自根目录《评估维度.csv》，
  `tests/test_api.py::test_weights_match_csv` 机器校验两者一致——改 CSV 或权重必须同步跑该测试）
- 老库启动自愈：`adaptability_score` 为 0 时用 expression_score 近似回填（database.py init_db）

### 领域约定（改代码前必读）

- **统一响应** `{code, message, data}`；错误码 0/40000/40100/40300/40400/40900/50000
  （app/core/exceptions.py 的 AppException 子类，HTTP 状态码自动对应）
- **受控词表单一来源**：题库 category（6 类：技术知识/系统设计题/场景题/编码与算法/项目深挖/行为面试）、
  difficulty、stage 常量定义在 `app/models/question.py`；`app/api/questions.py` 校验非法值返回 400
  （题库改名后立刻报错而非静默空集）。改词表只改 question.py，查询接口与导入脚本自动跟随
- **状态机**：面试 status 由 `app/core/state_machine.py` 表驱动（idle→in_progress→finished），
  非法转换抛 409；QA 记录"出题即落库、作答回填"
- **题库流水线**：`题库/*.xlsx`（V4，16 列含 expression_points）→ `backend/scripts/import_question_bank.py`
  （幂等重跑；剥离题干内嵌软技能标签到 soft_skill_tag 列）→ questions 表；
  Excel 规范/导入/排障/加岗流程给 P5 的完整手册 = `docs/reports/REPORT_TO_P5.md`

## 环境与部署铁律（踩过血的坑）

- **端口**：8001=主后端、8002=P3 评估、5273=演示前端（start.py 自动拉起）；
  **8000 被本机 Godot AI MCP 占用，勿改回**；5173 是 P4 Vite 联调端口，start.py 不会占用
- **`backend/start.bat` 必须 CRLF 行尾且纯 ASCII**（无中文注释/echo）——cmd 对 LF-only 或中文 REM
  解析错乱；`.gitattributes` 已设 `*.bat -text`。改后校验：
  `python -c "open('backend/start.bat','rb').read().count(b'\r\n')"` 应等于行数；中文提示放 start.py
- **内网穿透**：Sakura Frp Web 隧道 + 自动 HTTPS，访问必须 https://（http 被 501 拦截），
  详见 docs/DEPLOY.md

## 双远程推送规则（每次提交必须执行）

| 远程 | 地址 |
| :--- | :--- |
| `origin` | https://github.com/yangziyue-c/ai-interview-system |
| `gitee` | https://gitee.com/yangziyuegit/ai-interview-system |

**每次 git commit 后必须同时推送到两个远程**（提交前先 `git pull origin main` 同步，内容保持一致）：

```bash
git push origin main && git push gitee main
```
