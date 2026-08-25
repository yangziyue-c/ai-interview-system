# Git 协作指南（5 人团队）

## 一、仓库信息

- 仓库地址：https://github.com/yangziyue-c/ai-interview-system
- 分支策略：
  - `main`：稳定分支，只接受合并请求/直接推送需团队约定
  - 每人功能分支：`feature/xxx`（如 `p2/rag-retrieval`、`p4/chat-ui`）

## 二、给其他成员开通提交权限

> 前提：成员先各自注册 GitHub 账号并把 **用户名** 发给你。

### 方法 A：网页操作（推荐，最简单）

1. 打开仓库页面 → 右上角 **Settings**
2. 左侧 **Collaborators**（新版为 Settings → Access → Collaborators）
3. 点击 **Add people** → 输入成员的 GitHub 用户名 → **Add**
4. 对方会收到一封 **邀请邮件**（或 GitHub 站内通知），**点击 Accept invitation** 后即获得写权限

### 方法 B：GitHub CLI（需要先安装 gh 并登录）

```bash
# 给每个成员发邀请（用户名按实际替换）
gh repo add-collaborator yangziyue-c/ai-interview-system p2_github_用户名 --permission push
gh repo add-collaborator yangziyue-c/ai-interview-system p3_github_用户名 --permission push
gh repo add-collaborator yangziyue-c/ai-interview-system p4_github_用户名 --permission push
gh repo add-collaborator yangziyue-c/ai-interview-system p5_github_用户名 --permission push
```

### 方法 C：组织仓库（5 人都同一学校组织时更规范）

1. GitHub 上创建 Organization（如 `xxx-comp-team`）
2. 把仓库 transfer 到组织，或直接在组织下新建仓库
3. 创建 Team（如 `dev`），把 4 名成员拉进 Team，给 Team 授 `Write` 权限
4. 好处：成员变更只改 Team 成员，不用逐个改仓库权限

## 三、成员的日常提交流程（写给 P2~P5）

```bash
# 1. 首次：克隆仓库（用发给你的仓库地址）
git clone https://github.com/yangziyue-c/ai-interview-system.git
cd ai-interview-system

# 2. 每次开发前：拉最新代码 + 建自己的分支
git checkout main
git pull origin main
git checkout -b p4/chat-ui          # 分支名换成自己模块

# 3. 开发、提交（多次）
git add .
git commit -m "feat(前端): 完成聊天界面布局"

# 4. 推送到远端自己的分支
git push -u origin p4/chat-ui

# 5. 到 GitHub 网页发 Pull Request（Compare & pull request），P1 审核后合并
```

### 冲突了怎么办

```bash
git checkout main
git pull origin main
git checkout p4/chat-ui
git merge main          # 解决冲突文件后：
git add .
git commit -m "merge: 同步 main 分支"
git push
```

## 四、协作约定（重要）

| 规则 | 说明 |
| :--- | :--- |
| 不要直接推 `main` | 一律走分支 + Pull Request，P1 审核合并 |
| `.env`、数据库文件不入库 | 已在 `.gitignore` 中忽略；本地自己复制 `.env.example` 为 `.env` |
| 每次提交前先 `git pull` | 减少冲突 |
| commit message 用中文+前缀 | `feat:` 新功能 / `fix:` 修复 / `docs:` 文档 / `test:` 测试 |
| 音频、大文件不入库 | 演示录音存本地 `backend/uploads/`，已被 gitignore |

## 五、克隆后如何跑起来

```bat
cd backend
双击 start.bat          （自动建 conda 环境 + 装依赖 + 启动）
```

详见根目录 [README.md](../README.md)。
