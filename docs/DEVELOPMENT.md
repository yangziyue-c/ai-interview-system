# 开发手册（本地开发与调试）

> **面向**：需要在本地跑测试、调试后端、改动启动脚本的成员。
> **互补关系**：Git 协作流程见 `COLLABORATION.md`，内网穿透演示见 `DEPLOY.md`。
> 本文只写**在任何机器上都成立的机制**；P1 本机的具体路径、端口占用等环境状态不在其中。

---

## 一、Python 环境

后端跑在 conda 环境 **`ai_interview`**（Python 3.12）下。

**`conda run` 有插件 bug**（表现为丢输出或挂起），不要用它包装命令；直接调用该环境内的 `python.exe`：

```bash
conda env list      # 1. 查环境实际位置
<PY> -m pytest      # 2. <PY> = 上一步查到的 .../envs/ai_interview/python.exe
```

下文所有命令中的 `<PY>` 均指该解释器。

---

## 二、测试

### 2.1 必须在 `backend/` 目录下运行

```bash
cd backend
<PY> -m pytest                                                          # 全量
<PY> -m pytest tests/test_question_bank.py -q                           # 单文件
<PY> -m pytest tests/test_api.py::TestAuth::test_login_wrong_password   # 单用例
```

**原因**：`pytest.ini`（`testpaths = tests`、`asyncio_mode = auto`）与
`tests/conftest.py` 的环境变量注入，都以 `backend/` 为工作目录才生效。
在仓库根目录跑，`pytest.ini` 不会被加载：`asyncio_mode` 缺失会让**异步用例集体报错**
（`async def functions are not natively supported`），conftest 的环境变量也不会注入。

`asyncio_mode = auto` 的含义：异步测试函数**无需**逐个标注 `@pytest.mark.asyncio`。

### 2.2 测试库隔离机制（`tests/conftest.py`）

conftest 在 **import app 之前**注入环境变量（顺序是关键，晚于 `app` 导入则失效）：

| 变量 | 测试期取值 | 目的 |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./test_interview.db` | 指向独立测试库 |
| `LLM_API_KEY` | 空 | 防止空库用例误调真实大模型 |
| `REDIS_URL` / `AI_INTERVIEWER_URL` / `AI_EVALUATOR_URL` | 空 | 禁用外部服务 |

**`RAG_API_URL` 需要单独说明**：它与上面三个不同——`config.py` 里默认为
`http://localhost:8003`，不清空的话每个「题库未命中」的用例都会真的去连本机 8003：
服务没起时白等探测超时，服务起了则拿到真实题目，**「空库降级 Mock」这类断言就失去了意义**。

每次测试会话开始时，旧的 `test_interview.db` 会被删除重建，保证用例可重复执行。
**测试全程不会碰开发库 `backend/interview.db`。**

### 2.3 造数工厂（`tests/helpers.py`）

刻意独立于 conftest —— conftest 是有环境副作用的 pytest 钩子文件，不该被测试模块当普通模块 import。

| 函数 | 用途 |
| :--- | :--- |
| `make_question(**overrides)` | 造 Question 记录：默认值铺底，只覆盖差异字段 |
| `make_follow_up_field(trigger, text)` | 构造 V5 格式追问字段（`[触发] …` + `[追问] …`） |

`make_question()` 的 `question_no` 默认带随机后缀：questions 表有
`(position_code, question_no)` 唯一约束，固定键二次插入会 `IntegrityError`，
随机后缀让调用方无需显式覆盖即可反复造数。

---

## 三、数据库并发（SQLite）

`app/database.py` 对 SQLite 做了两层配置：

```python
# 1. 引擎参数
connect_args = {"check_same_thread": False, "timeout": 30}   # 异步场景需关线程检查

# 2. 每个连接建立时（event.listens_for connect）
PRAGMA journal_mode=WAL      # WAL 下读不阻塞写
PRAGMA busy_timeout=30000    # 并发写等待锁释放，而非立刻抛 database is locked
```

**目的**：两场面试同时提交答案时不会锁库报错。

### 适配器的只读短会话（改代码前必读）

`app/adapters/ai_interviewer.py` 的题库查询**自开独立短会话**，刻意不复用请求级会话：

> 请求会话里可能有尚未提交的脏写（答案 / 轮次），在该会话内执行 SELECT 会触发
> **autoflush**，把写锁提前到「出题全程」——包含网络级降级源的等待时间。

所以：**不要为了省一次会话，把请求级 `db` 传进适配器**。独立短会话 + WAL 下读不阻塞写。

---

## 四、超时预算分档

| 层级 | 超时 | 定义位置 |
| :--- | :--- | :--- |
| RAG 语义检索 | **60 秒** | `app/config.py::RAG_TIMEOUT_SECONDS` |
| P3 评估服务 | **30 秒** | `app/adapters/ai_evaluator.py::EVALUATE_TIMEOUT_SECONDS` |
| 其余 HTTP/LLM 适配器 | **15 秒** | `app/config.py::ADAPTER_TIMEOUT_SECONDS` |

RAG 单独放宽的原因：单次 `/rag/search` 含 Top-20 reranker 精排，CPU 上实测 **20~30 秒**
（向量召回本身仅 0.1 秒，瓶颈全在 reranker）。**不要按普通接口把它设成个位数秒**——
那会让每次检索都被误判为「RAG 不可用」而白白降级。

> P3 评估的 30 秒写死在 `ai_evaluator.py` 内，**不经过** `ADAPTER_TIMEOUT_SECONDS`，
> 改通用档不会影响它。

---

## 五、`start.bat` 编码铁律

`backend/start.bat` 必须同时满足两条：

1. **CRLF 行尾** —— cmd 对 LF-only 的 bat 解析会出错
2. **纯 ASCII** —— 不能有中文注释或 `echo`（中文提示放 `start.py`）

`.gitattributes` 用 `*.bat -text` 来保证：

```
*.bat -text
```

用 `-text`（禁止行尾转换）而不是 `text eol=crlf` 的原因：前者让 CRLF **原样存入仓库**，
因此 GitHub 的 Download ZIP 导出也是 CRLF；后者只在 `clone` 时转换，**zip 导出会变成 LF**。

改动后校验（行数应等于 CRLF 数，非 ASCII 字节数应为 0）：

```bash
python -c "
d = open('backend/start.bat','rb').read()
print('总行数', d.count(b'\n'), '| CRLF', d.count(b'\r\n'), '| 非ASCII字节', sum(1 for b in d if b >= 128))
"
```

---

## 附：常见问题

| 现象 | 原因 / 处理 |
| :--- | :--- |
| `ModuleNotFoundError: No module named 'app'` | 在仓库根目录跑了脚本；`cd backend` 后再跑，或用 `-m` 方式（如 `-m scripts.import_question_bank`） |
| 测试连上了真实大模型 / 外部服务 | conftest 未生效：确认在 `backend/` 下运行，且 `app` 是在环境变量注入之后才被 import |
| `database is locked` | 检查是否绕过了 WAL 配置，或把请求级会话传进了适配器（见第三节） |
| `conda run` 无输出 / 卡住 | 已知插件 bug，改用环境内 `python.exe` 直调（见第一节） |
