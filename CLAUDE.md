# CLAUDE.md — AI 模拟面试系统项目指令

## 双远程推送规则（每次提交必须执行）

本项目同时托管在两个远程（Gitee 供国内网络稳定访问）：

| 远程名 | 地址 |
| :--- | :--- |
| `origin` | https://github.com/yangziyue-c/ai-interview-system |
| `gitee` | https://gitee.com/yangziyuegit/ai-interview-system |

**每次 git commit 后必须同时推送到两个远程：**

```bash
git push origin main && git push gitee main
```

提交前先 `git pull origin main` 同步，避免冲突。两个远程内容必须保持一致。

## 项目关键信息

- **运行环境**：conda 环境 `ai_interview`（Python 3.12）。注意：本机 `conda run` 有插件 bug，直接调用环境内 python.exe；环境真实位置用 `conda env list` 查询（可能在用户目录 `.conda/envs`，不要按 base/envs 猜路径）
- **服务端口**：8001（8000 被本机 Godot AI 工具的 godot_ai MCP 服务占用，勿改回）
- **启动方式**：双击 `backend/start.bat`（纯 ASCII 引导器，主逻辑在 `backend/start.py`）；手动方式 `cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001`
- **测试**：`cd backend && <ai_interview的python.exe> -m pytest`（11 个用例，测试库 test_interview.db）
- **内网穿透**：Sakura Frp Web 隧道 + 自动 HTTPS，访问必须 https://（http 被 501 拦截），详见 docs/DEPLOY.md

## 文件编码铁律（踩过血的坑）

- **`backend/start.bat` 必须是 CRLF 行尾且纯 ASCII**（无中文注释/echo）：cmd 对 LF-only 或含中文 REM 的 bat 解析错乱。`.gitattributes` 已设 `*.bat -text` 保证 CRLF 原样入库
- 修改 start.bat 后必须确认 CRLF：`python -c "open('backend/start.bat','rb').read().count(b'\r\n')"` 应等于行数
- 不要在任何 bat 中添加中文（中文提示放 start.py 或文档里）
