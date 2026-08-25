# Git 协作指南（5 人团队）

## 一、仓库信息

- 仓库地址：https://github.com/yangziyue-c/ai-interview-system
- 分支策略：所有成员直接推 `main` 分支（团队人数少，功能模块不重叠，直推最省事）

## 二、成员的日常提交流程（写给 P2~P5）

```bash
# 1. 首次：克隆仓库
git clone https://github.com/yangziyue-c/ai-interview-system.git
cd ai-interview-system

# 2. 每次开发前：拉最新代码
git pull origin main

# 3. 开发、提交
git add .
git commit -m "feat(前端): 完成聊天界面布局"

# 4. 直接推送到 main
git push origin main
```

### 冲突了怎么办

push 被拒绝（`rejected`）说明远端有新提交，按下面流程解决：

```bash
git pull origin main          # 自动合并；若提示 CONFLICT，手动编辑冲突文件
# 解决冲突后：
git add .
git commit -m "merge: 同步远端最新代码"
git push origin main
```

## 三、协作约定（重要）

| 规则 | 说明 |
| :--- | :--- |
| 推送前先 `git pull` | 减少冲突，冲突解决流程见上 |
| `.env`、数据库文件不入库 | 已在 `.gitignore` 中忽略；本地自己复制 `.env.example` 为 `.env` |
| API key 严禁提交 | `LLM_API_KEY` 等只放本地 `.env`，commit 前检查 `git status` |
| commit message 用中文+前缀 | `feat:` 新功能 / `fix:` 修复 / `docs:` 文档 / `test:` 测试 |
| 音频、大文件不入库 | 演示录音存本地 `backend/uploads/`，已被 gitignore |

## 四、克隆后如何跑起来

```bat
cd backend
双击 start.bat          （自动建 conda 环境 + 装依赖 + 启动）
```

详见根目录 [README.md](../README.md)。
