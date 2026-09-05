# P2 联调教程：主后端题库 API（含可运行示例）

> 写给 P2（后端开发 B）。本文档教你**从主后端拉取题库数据**（3 岗位 × 150 题，已入库 `questions` 表），
> 供你的 AI 面试官服务选题/追问使用。接入契约（你的服务如何被主后端调用）见
> [REPORT_TO_P2.md](REPORT_TO_P2.md)，代码整改见 [P2_CODE_REVIEW.md](P2_CODE_REVIEW.md)。
>
> **2026-09-04 已实测全流程通过**：服务运行于 `http://localhost:8001`，服务账号 `p2_service` 已注册好。

## 0. 前置条件

- 主后端服务运行中：`http://localhost:8001`（健康检查 `GET /api/v1/health` 返回 `healthy`）
- 服务账号已注册好（也可自己注册）：
  - 用户名：`p2_service`
  - 密码：`p2pass123456`
- access_token 有效期 24 小时（`JWT_EXPIRE_MINUTES=1440`），过期后重新登录即可

## 1. 统一响应格式

所有接口返回 `{code, message, data}`：

```json
{"code": 0, "message": "ok", "data": { ... }}
```

| code | 含义 |
| :--- | :--- |
| 0 | 成功 |
| 40000 | 参数错误（如 stage 词表写错） |
| 40100 | 未登录 / token 失效 |
| 40300 | 无权限 |
| 40400 | 资源不存在 |
| 40900 | 状态冲突 |
| 50000 | 服务器内部错误 |

## 2. 鉴权：注册 / 登录

所有题库接口都需要 `Authorization: Bearer <access_token>` 请求头，不带或失效返回 `401`。

```python
import requests

BASE = "http://localhost:8001/api/v1"

# 方式一：登录（账号已注册好时用这个）
r = requests.post(f"{BASE}/auth/login", json={
    "username": "p2_service", "password": "p2pass123456",
})
TOKEN = r.json()["data"]["access_token"]

# 方式二：注册新账号（注册即自动登录，返回 access_token）
r = requests.post(f"{BASE}/auth/register", json={
    "username": "p2_service",        # 3~32 字符
    "password": "p2pass123456",      # 6~64 字符
    "nickname": "P2服务账号",         # 可选
    "target_position": "backend",    # 默认 backend；有效值 backend/frontend/test_engineer
})
TOKEN = r.json()["data"]["access_token"]

HEADERS = {"Authorization": f"Bearer {TOKEN}"}
```

> 你的服务建议：**启动时登录一次拿 token，请求返回 401 时自动重新登录**，不要每次请求都登录。

## 3. 题库接口

### 3.1 题目列表（分页）

```
GET /api/v1/questions?position=backend&difficulty=easy&stage=开场热身&limit=20&offset=0
```

查询参数（全部可选）：

| 参数 | 说明 | 可选值 |
| :--- | :--- | :--- |
| position | 岗位 code | backend / frontend / test_engineer |
| category | 大类 | 技术知识 / 场景与设计 / 编码与算法 / 项目深挖 / 行为面试 |
| difficulty | 难度 | easy / medium / hard |
| stage | 面试阶段 | 开场热身 / 核心考察 / 深度考察 / 收尾交流 |
| q | 题干模糊搜索 | 任意关键词 |
| limit | 每页条数 | 1~100（**最大 100**，默认 20） |
| offset | 偏移量 | ≥0（翻页用） |

> ⚠️ category / difficulty / stage 是受控词表，**写错返回 400（code 40000）**，不会静默返回空集。

返回结构（题目在 `data.items`）：

```json
{
  "code": 0, "message": "ok",
  "data": { "total": 150, "items": [ { ...题目字段... } ] }
}
```

题目字段（实测 17 个，**你主要用加粗项**）：

| 字段 | 说明 |
| :--- | :--- |
| **question** | 题干（已剥离软技能标签，可直接读给候选人） |
| **follow_up_triggers** | 追问触发条件（L1/L2/L3/降级四段文本，解析见 [P2_CODE_REVIEW.md](P2_CODE_REVIEW.md) 第 3 条） |
| **interview_stage** / stage_order | 面试阶段（开场热身→核心考察→深度考察→收尾交流）/ 顺序 1~4 |
| **difficulty** | easy / medium / hard |
| **position_code** | 岗位 code（与请求参数 position 一致） |
| question_no | 题库编号（tech_001 等，岗位内唯一） |
| category / sub_category | 大类 / 题目分类（如 Java基础） |
| soft_skill_tag | 软技能考察标签（仅选题参考，**勿读给候选人**） |
| score_points | 得分点 `【basic 0.3】【core 0.5】【advanced 0.2】`（可作评分 Prompt 上下文） |
| reference_answer | 参考答案 |
| alternative_directions | 替代回答方向（追问素材） |
| excellent_example | 优秀回答范例 |
| note | 备注（如"高频考点""适合面试开场"） |
| suggested_minutes | 建议用时（仅参考，与轮次无关） |

### 3.2 题目详情

```
GET /api/v1/questions/{question_id}   # items 里的 id 字段
```

## 4. 完整可运行示例：启动时全量拉取 450 题缓存

建议你的服务**启动时全量拉取一次、缓存到内存**，运行时不再请求后端：

```python
import requests

BASE = "http://localhost:8001/api/v1"


def get_token() -> str:
    """登录拿 token；失败则注册"""
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": "p2_service", "password": "p2pass123456"},
                      timeout=10)
    if r.status_code == 200:
        return r.json()["data"]["access_token"]
    r = requests.post(f"{BASE}/auth/register",
                      json={"username": "p2_service", "password": "p2pass123456",
                            "nickname": "P2服务账号", "target_position": "backend"},
                      timeout=10)
    return r.json()["data"]["access_token"]


def load_question_bank() -> dict[str, list[dict]]:
    """按岗位全量拉取，返回 {position: [题目, ...]}"""
    headers = {"Authorization": f"Bearer {get_token()}"}
    bank: dict[str, list[dict]] = {}
    for position in ("backend", "frontend", "test_engineer"):
        items, offset = [], 0
        while True:
            r = requests.get(f"{BASE}/questions",
                             params={"position": position, "limit": 100, "offset": offset},
                             headers=headers, timeout=10)
            r.raise_for_status()          # 401 时重新登录重试（自己封装一层即可）
            data = r.json()["data"]
            items.extend(data["items"])
            if offset + 100 >= data["total"]:
                break
            offset += 100
        bank[position] = items
        print(f"{position}: {len(items)} 题")
    return bank


def pick(bank: dict, position: str, stage: str, difficulty: str | None = None,
         exclude: set[str] = set()) -> str | None:
    """按阶段（可加难度）随机抽一题，排除本场已问题目"""
    import random
    pool = [q for q in bank.get(position, [])
            if q["interview_stage"] == stage
            and (difficulty is None or q["difficulty"] == difficulty)
            and q["question"] not in exclude]
    if not pool:
        return None
    return random.choice(pool)["question"]


if __name__ == "__main__":
    bank = load_question_bank()
    # 开场题：开场热身 + easy（每岗 21 题，实测）
    print("开场题:", pick(bank, "backend", "开场热身", "easy"))
    # 收尾题：收尾交流（每岗 15 题）
    print("收尾题:", pick(bank, "backend", "收尾交流"))
```

选题约定（与 [REPORT_TO_P2.md](REPORT_TO_P2.md) 一致）：

- **开场题（round=1）**：`stage=开场热身` 且 `difficulty=easy`
- **追问（round=2~7）**：按上一题的 `follow_up_triggers` 驱动（L1 关键词 → L2 递进 → L3 极限 → 降级策略，解析与层级推断见 [P2_CODE_REVIEW.md](P2_CODE_REVIEW.md)）
- **换新题**：优先 `核心考察` → `深度考察` 递进
- **收尾（round=6/7）**：`stage=收尾交流`

## 5. 常见坑（实测踩过）

| 现象 | 原因 | 解法 |
| :--- | :--- | :--- |
| Windows 下 `curl -d '{"...中文..."}'` 报 `error parsing the body` | Git Bash/cmd 对中文 JSON 的编码坑 | 用 Python `requests`/`httpx`，或浏览器打开 `http://localhost:8001/docs`（Swagger 在线调试） |
| 直接浏览器访问题库接口 401 | 接口需要 Bearer token | 按第 2 节登录拿 token |
| `limit=150` 返回 422 | limit 上限 100 | 用 `limit=100` + `offset` 翻页 |
| `stage=破冰环节` 返回 400 | stage 是受控词表 | 用第 3.1 节表格里的可选值 |
| 拿到 40100 | token 过期（24h）或没带 header | 重新登录拿新 token |

## 6. 接入契约速查（你的服务如何被主后端调用）

主后端调用你的服务（在 `backend/.env` 配置 `AI_INTERVIEWER_URL=http://你的地址` 后生效）：

```
POST {你的服务}/generate
{
  "position": "backend",
  "round": 2,
  "is_follow_up": true,
  "history": [
    {"role": "interviewer", "content": "..."},
    {"role": "candidate", "content": "..."}
  ]
}
→ 期望返回 {"question": "下一题文本"}
```

- 岗位是动态 code（backend / frontend / test_engineer），**不要写死岗位列表**
- 后端 15 秒未收到响应 / 非 2xx 会自动降级内置 Mock，面试流程不会中断——**你的服务可以放心迭代**
- 完整约定见 [REPORT_TO_P2.md](REPORT_TO_P2.md)

## 7. 联调验收清单

1. ✅ 启动时全量拉取成功：三岗位各 150 题
2. ✅ `POST /generate`（round=1）返回开场热身 + easy 题
3. ✅ 追问触发：候选人回答含 L1 关键词 → 返回对应追问；连续追问依次走 L2 → L3 → 换新题
4. ✅ round=6/7 返回收尾交流题
5. ✅ 主后端 `.env` 配 `AI_INTERVIEWER_URL` 后，完整面试 7 轮走通并自动出报告
6. ✅ 主后端回归：`cd backend && pytest`（不配 URL 时走内置 Mock，11 个用例全绿）
