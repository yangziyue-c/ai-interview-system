# AI 模拟面试系统（前端部分）

Vue 3 + Vite 构建的 Web 前端，对接主后端 8001。

## 项目能力

### 认证与用户

- 注册 / 登录，密码可显示或隐藏
- 编辑资料
- 更换头像（本地预览后上传）
- 退出登录

### 面试流程

- 岗位大厅：从接口拉取岗位列表
- 岗位详情：技术栈、考察重点
- 面试对话室：与 AI 面试官一问一答
- 断点续答：中途退出，下次能继续。引擎链路下追问记录也一起还原
- 主动结束：二次确认，一题未答时拦截

### 语音与姿态

前端负责采集与交互，后端负责识别与分析。

**语音输入**

用户点击"点击说话"开始录音。录音期间，Vosk 在浏览器本地实时识别：中间结果显示在输入框下方的提示行，识别完成后填入输入框，用户可在发送前修改。停止录音（再次点击）后，用 MediaRecorder 录制的 webm 音频上传至后端 ASR 接口，后端返回一次更准确的转写文本与一组表达读数；返回的文本覆盖输入框供用户校对，表达读数随答案提交。识别过程在本地完成，音频只在停止录音时上传一次。

**语音朗读**

AI 的题目与追问可朗读。前端把文本发给后端 TTS 接口，拿到音频 URL 后播放。顶栏有自动播报开关，默认开启，状态存在本地。每条消息旁也有手动朗读按钮。

**摄像头追踪**

浏览器本地提取姿态关键点，只把数字坐标传给后端，视频画面不出本机。后端返回姿态信号后，桌面端在右侧面板展示、移动端为输入框上方的画中画小窗。

### 报告与分享

- 五维雷达图
- 成长曲线（按岗位切分）
- 综合评语、优点、待改进
- 学习计划
- 评分不完整提示
- 导出为图片、生成免登录分享链接
- 问答历史（气泡展示、可复制全文）

### 题库与简历

- 题库中心：搜索、岗位筛选、难度筛选、分页加载
- 简历：上传 PDF / 图片，显示解析状态与识别结果

### 全局与兜底

- 路由守卫（未登录跳登录页，已登录访问登录页跳选入页，未选模块访问主页面跳选入页）
- 404 页面：访问不存在的路径时显示，提供"返回上一页"与"返回首页"
- Mock / 真接口一键切换
- 桌面端与移动端响应式
- 设置面板（占位）

## 快速开始

### 环境要求

- Node.js 20+
- npm 10+

> 本项目在 Node 24.20.0 + npm 11.19.0 下验证通过。Vite 8 对 Node 有最低版本要求，请勿低于 Node 20。

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run dev
```

默认跑在 `http://localhost:5173`。

### 构建生产版本

```bash
npm run build
```

构建产物在 `dist/` 目录。

### 本地预览构建产物

```bash
先执行 npm run build，再：
npm run preview
```

---

## 环境变量

项目根目录有 2 个环境变量文件：

### `.env.development`（开发环境）

```
VITE_API_BASE=http://100.95.145.0:8001/api/v1
VITE_ASSET_BASE=http://100.95.145.0:8001
```

- `VITE_API_BASE`：后端接口地址，开发时连 1 号的 Tailscale IP
- `VITE_ASSET_BASE`：静态资源地址（头像、录音、TTS 音频）

如果后端跑在本机，改成：

```
VITE_API_BASE=http://localhost:8001/api/v1
VITE_ASSET_BASE=http://localhost:8001
```

### `.env.production`（生产/部署环境）

```
VITE_API_BASE=/api/v1
VITE_ASSET_BASE=
```

部署时前端与后端同源，走相对路径。

### 修改后需要重启 dev server

环境变量只在启动时读取，改完要 `Ctrl+C` 停掉再 `npm run dev`。

---

## 静态资源依赖

`public/` 目录下有 4 个必需资源：

| 文件/目录                                           | 用途                       | 大小     |
| --------------------------------------------------- | -------------------------- | -------- |
| `public/model.tar.gz`                               | Vosk 中文语音识别模型      | 约 40MB  |
| `public/vendor/mediapipe/vision_bundle.js`          | MediaPipe 运行时           | 约 200KB |
| `public/vendor/mediapipe/wasm/`                     | MediaPipe WebAssembly 模块 | 约 3MB   |
| `public/vendor/mediapipe/pose_landmarker_lite.task` | MediaPipe 姿态模型         | 约 5MB   |

**关于 Vosk**：Vosk 是浏览器端离线语音识别引擎，代码里加载的是 `model.tar.gz`（约 40MB）。面试时用户点击"点击说话"开始录音，Vosk 在本地实时识别，中间结果显示在提示行，识别完成后填入输入框。停止录音后，录制的音频会上传一次给后端 ASR 做更准确的转写。缺这个文件，语音输入用不了。

**关于 MediaPipe**：摄像头追踪用。浏览器本地提取姿态关键点，只把数字坐标传给后端，视频画面不出本机。缺这些文件，摄像头功能用不了。

**来源**：

- `vendor/mediapipe/`：从 5 号的对话层交付包 `backend/dialogue_layer/web/vendor/mediapipe/` 复制
- `model.tar.gz`：Vosk 中文小模型，单独获取

**验证**：`npm run build` 后，检查 `dist/` 里是否也有这些文件。

---

## 部署

### 开发联调

前端跑 Vite（5173），后端跑 8001。浏览器访问 `http://localhost:5173`。

### 演示部署

```bash
# 1. 构建
npm run build

# 2. 把 dist/ 里所有内容拷到后端静态目录
cp -r dist/* backend/static/

# 3. 让后端重启（静态目录是启动时挂载的）

# 4. 访问
#    http://<后端地址>:8001
```

每次改前端代码后都要重新 `npm run build` + 拷贝 + 重启后端。

---

## 项目结构

```
src/
├── api/            接口层（每个模块含 Mock 与真接口分支）
├── assets/         静态资源（构建期处理）
├── components/     全局组件
├── composables/    组合式函数
├── config/         环境变量、岗位图标等配置
├── router/         路由与守卫
├── styles/         设计系统变量
├── utils/          请求封装、Toast、Confirm 等
└── views/          页面

public/
├── favicon.svg               标签页图标
├── model.tar.gz              Vosk 模型
├── jobs.json                 岗位数据
└── vendor/mediapipe/         MediaPipe 资源
```

---

## Mock 模式

`src/api/_config.js` 里的 `USE_MOCK` 开关：

- `true`：所有接口走本地 Mock 数据，不需要后端
- `false`：走真接口（联调/部署必须）

部署前确认为 `false`。