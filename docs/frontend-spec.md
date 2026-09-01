
---

# 模拟面试系统前端需求与接口文档

## 一、前端整体框架

采用 **底部固定 Tab 栏** 布局，共包含 2 个 Tab：**模拟面试** 和 **个人中心**。  
技术栈：Vue（网页端开发，后续打包为桌面/移动应用）

---

### Tab1：模拟面试

#### ① 岗位大厅
- 展示至少 2 个岗位卡片（如：Java 后端、Web 前端）。
- 点击卡片 **不直接进入对话**，而是弹出 **岗位详情浮层** 或跳转至 **岗位详情页**。

#### ② 岗位详情页
- 展示内容：
  - 技术栈要求
  - 面试考察重点
- 底部提供显眼的 **“开始面试”** 按钮。

#### ③ 面试对话室（核心页面）
1. **顶部**：显示面试进行中的状态（如“面试中”、“第3题”等）。
2. **中间**：聊天区域
   - AI 消息气泡靠左
   - 用户回答气泡靠右
3. **底部输入区**：
   - 左侧：语音录制按钮（按住说话）
   - 右侧：文本输入框 + 发送按钮
   - 支持语音/文本 **随时切换使用**

---

### Tab2：个人中心

1. **上半部分**：用户头像、昵称、学号
2. **中间部分**：历史面试列表（按时间倒序）
   - 每条记录显示：`岗位名称 + 综合得分 + 面试日期`
   - 点击可进入该次面试的 **完整评估报告**
3. **下半部分**：当前最新建议
   - 显示最近一次 AI 评价给出的改进建议

---

## 二、数据接口规范

> **通用约定**：
> - 身份验证：登录成功后将 `token` 存入 `localStorage`，后续所有请求在 Header 中携带  
>   `Authorization: Bearer {token}`
> - 跨域处理：后端需配置 CORS，允许前端本地开发地址（如 `http://localhost:5173`）访问
> - 语音格式：浏览器原生录音 API 录制 WAV 文件，采样率 16000Hz

---

### （一）业务接口（对接 1 号后端）

#### 1. 登录接口
- **方法**：`POST`
- **路径**：`/api/auth/login`
- **请求体**：
  ```json
  {
    "username": "string",
    "password": "string"
  }
  ```
- **响应示例**：
  ```json
  {
    "code": 0,
    "data": {
      "userId": 1001,
      "realName": "张明",
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }
  }
  ```
- **说明**：`code === 0` 表示成功，非 0 表示失败

#### 2. 开始面试接口
- **方法**：`POST`
- **路径**：`/api/interview/start`
- **Header**：`Authorization: Bearer {token}`
- **请求体**：
  ```json
  {
    "jobId": "java-backend"
  }
  ```
- **响应**：
  ```json
  {
    "code": 0,
    "data": {
      "sessionId": "sess_abc123",
      "firstQuestion": "请介绍一下你最近做的项目..."
    }
  }
  ```

#### 3. 提交回答接口（SSE 流式）
- **方法**：`POST`
- **路径**：`/api/interview/answer`
- **Header**：`Authorization: Bearer {token}`
- **请求体**：
  ```json
  {
    "sessionId": "sess_abc123",
    "answerType": "text | voice",
    "content": "用户输入的文本或语音转文字结果"
  }
  ```
- **响应**：Server-Sent Events（SSE）流
  - 每条数据为 JSON 对象：
    - `type: "delta"` → `content` 为 AI 回复片段
    - `type: "end"` → `content` 为结束原因，前端关闭连接并跳转报告页

#### 4. 历史记录列表接口
- **方法**：`GET`
- **路径**：`/api/interview/history`
- **Header**：`Authorization: Bearer {token}`
- **响应**：
  ```json
  {
    "code": 0,
    "data": [
      {
        "sessionId": "sess_abc123",
        "jobName": "Java 后端开发",
        "score": 85,
        "date": "2026-08-30"
      }
    ]
  }
  ```

---

### （二）AI 能力接口（对接 3 号后端）

#### 1. 语音转文字（ASR）接口
- **方法**：`POST`
- **路径**：`/api/asr/recognize`
- **Header**：`Authorization: Bearer {token}`
- **请求体**：`FormData`
  - `audio`: WAV 文件（16000Hz 采样率）
- **响应**：
  ```json
  {
    "code": 0,
    "data": {
      "text": "识别出的完整文字内容"
    }
  }
  ```
- **使用说明**：获取 `text` 后，再调用 `/api/interview/answer` 接口提交

#### 2. 评估报告详情接口
- **方法**：`GET`
- **路径**：`/api/report/detail?sessionId={sessionId}`
- **Header**：`Authorization: Bearer {token}`
- **响应**：
  ```json
  {
    "code": 0,
    "data": {
      "radarLabels": ["技术正确性", "逻辑严谨性", "岗位匹配度", "表达能力", "应变能力"],
      "radarValues": [88, 76, 90, 82, 70],
      "score": 85,
      "suggestions": [
        "建议加强并发编程的实际案例描述",
        "注意回答结构的条理性"
      ],
      "trend": [72, 78, 85]
    }
  }
  ```

---

### （三）岗位静态数据（对接 5 号）

提供只读岗位列表，**无需增删改**。

- **方式任选其一**：
  - 静态 JSON 文件置于前端 `public/jobs.json`
  - 或提供 GET 接口：`/api/job/list`

- **数据格式**：
  ```json
  [
    {
      "jobId": "java-backend",
      "jobName": "Java 后端开发",
      "techStack": "Spring Boot、MySQL、Redis、消息队列",
      "examFocus": "项目经验深挖、并发编程理解、性能优化思路"
    },
    {
      "jobId": "web-frontend",
      "jobName": "Web 前端开发",
      "techStack": "Vue3、TypeScript、Webpack/Vite、CSS 工程化",
      "examFocus": "组件设计能力、性能优化实践、工程化思维"
    }
  ]
  ```

---

## 三、协作确认事项

| 事项 | 负责方 | 说明 |
|------|--------|------|
| CORS 配置 | 1 号后端 | 允许前端本地开发地址访问 |
| 语音格式兼容 | 3 号后端 | 确认 ASR 接口支持 WAV@16000Hz |
| Token 解析 | 1/3 号后端 | 统一从 `Authorization: Bearer {token}` 中提取验证 |

--- 

> 本文档可作为前后端联调依据，请各端同学对照实现并及时同步变更。