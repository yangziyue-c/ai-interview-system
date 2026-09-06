# frontend_test —— AI 模拟面试演示前端

零构建的纯 HTML/CSS/JS 单页前端，用于快速查看项目整体实现。接口全部对照
[docs/API.md](../docs/API.md) 与 [docs/reports/REPORT_TO_P4.md](../docs/reports/REPORT_TO_P4.md)
实现，无任何第三方依赖，双击即可运行。

## 运行方式

**推荐：双击 `backend/start.bat` 一键启动**——启动器会自动拉起演示前端
（端口 5273，避开 P4 联调用的 5173）+ P3 评估服务（8002）+ 主后端（8001），
并在完成后打印访问指引（含本机与局域网地址）。

也可以先启动后端，再手动起前端：

```
cd backend && 双击 start.bat      # 或 python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

| 方式 | 命令 | 地址 |
| :--- | :--- | :--- |
| ① 静态服务器（推荐，跨域已由后端放开） | 本目录下 `python -m http.server 5273` | http://localhost:5273 |
| ② 同端口挂载（模拟正式部署） | 把本目录所有文件拷入 `backend/static/` | http://localhost:8001 |
| ③ 直接双击 | 打开 `index.html`（file:// 协议，麦克风可能受限） | —— |

> 方式 ①/③ 下前端直连 `http://<同一主机>:8001/api/v1`（后端 CORS 已 `allow_origins: ["*"]`，
> 局域网手机访问时自动指向所访问主机的 8001）；方式 ② 及任何同端口/隧道部署自动改用
> 相对路径 `/api/v1`，无跨域。

## 功能清单（对照 REPORT_TO_P4 页面需求）

- **登录 / 注册**：注册含昵称、学号（选填）；`GET /positions` 需登录态，
  故注册时不选岗位（后端默认 `backend`），开始面试时再选。
- **岗位大厅**：数据来自 `GET /positions`（未硬编码岗位列表）。
- **岗位详情**：简介 / 技术栈 / 考察重点 + 「开始面试」按钮。
- **面试对话室**：AI 左、用户右气泡；顶部「第 N/7 题」与「结束面试」按钮；
  文本输入（回车发送）；**按住说话**语音输入（Web Speech 转写 + MediaRecorder
  录 webm 上传 `POST /uploads/audio`，audio_url 随答案提交）；
  提交后按 `finished` 字段判断下一题或跳报告；
  已存在进行中面试（409）自动引导继续；刷新/重新进入可恢复会话。
- **报告页**：总分 + 5 维雷达图（原生 canvas）+ 评语/优势/不足/建议 +
  能力成长曲线（`GET /reports/growth`，≥2 场时绘制）。
- **个人中心**：昵称首字母头像 / 学号 / 目标岗位、历史面试列表
  （进行中可继续、已完成看报告、附得分）、最近一次改进建议（`GET /reports/latest`）、
  退出登录。

## 文件结构

```
frontend_test/
├── index.html      # 页面骨架（单页 + 底部 Tab 栏容器）
├── css/style.css   # 全部样式（移动端优先，桌面 520px 居中）
└── js/
    ├── api.js      # fetch 封装：BaseURL 自适应 / Bearer 鉴权 / {code,message,data} 解析
    ├── audio.js    # 语音：Web Speech 转写 + MediaRecorder 录音上传
    ├── charts.js   # canvas 雷达图 / 成长曲线
    ├── views.js    # 各视图 render + mount（登录注册/大厅/详情/对话室/报告/个人中心）
    └── app.js      # 全局状态 / hash 路由 / 登录守卫 / Tab 栏 / Toast
```

## 已知限制

- 语音转写依赖浏览器 Web Speech 服务（Chrome/Edge 可用，需要联网）；不支持时
  仍可录音上传或纯文本作答。
- `file://` 直接打开时浏览器可能禁用麦克风，建议用方式 ①。
- 后端在题库存量外的岗位或服务异常时会降级 Mock 出题/评分，前端无需感知。
