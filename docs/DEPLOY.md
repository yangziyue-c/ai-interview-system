# 部署与联调说明

> 本文覆盖两类场景，按需要看：
> **异地组员联调**（前端 ↔ 后端 ↔ 对话层引擎，走 Tailscale 虚拟内网）见「Tailscale 虚拟组网」；
> **对外公网演示**（评委/观众用手机流量访问）见「Sakura Frp」与「NatApp」。
> 同一 WiFi 下的演示见最后一节。

目标：让评委/观众在任何网络（手机流量、校园网外）通过公网地址访问你笔记本上运行的后端。

本项目的后端已做好配合：

- 启动时绑定 `0.0.0.0`（监听所有网卡）
- CORS 已配置为通配符 `*`（任何来源的前端页面都可调用 API）
- 前后端同端口（前端 dist 由后端挂载），穿透一个端口即可访问全部功能

> 前置条件：后端已通过 `start.bat` 启动在 8001 端口。
> 验证本机连通性：浏览器打开 `http://localhost:8001/api/v1/health`。
>
> 端口约定：**8001 = 主后端**（FastAPI，对外服务，穿透映射此端口）；
> **8002 = P3 AI 评估服务**（Flask，由 start.py 自动拉起，仅供主后端本机调用，
> 不参与穿透、无需暴露公网）；
> **8003 = RAG 检索服务**（由 start.py 自动拉起，首次启动需下载约 4.5GB 模型；
> 与 8002 一样仅供主后端本机调用，不参与穿透）；
> **5273 = 演示前端**（frontend_test/，start.py 自动拉起的静态服务，仅本机/局域网用）。

## 公网演示带上前端页面

本项目前端（`frontend_test/`）默认跑在独立端口 5273，穿透只映射 8001 时公网访问不到
5273 的页面（只能访问 Swagger/接口）。公网要展示完整页面，二选一：

| 方式 | 做法 | 结果 |
| :--- | :--- | :--- |
| ① 同端口挂载（推荐，免第二隧道） | 把 `frontend_test/` 全部文件拷入 `backend/static/`（覆盖占位 index.html），重启 start.bat | `https://xxx.natfrp.cloud/` 直接打开前端页面，页面同源请求 `/api/v1` 无需跨域 |
| ② 再开一条隧道 | 新增一条 Web 隧道指向本地 `127.0.0.1:5273` | `https://xxx2.natfrp.cloud` 打开前端，跨域访问 8001（后端 CORS 已全开） |

> 方式 ① 下若前端页面打开正常但接口 404，确认地址后不要加端口（前端已自动走相对路径）。
> P4 正式前端交付后把构建产物拷入 `backend/static/`，形态与方式 ① 完全一致。

---

## 方案一：Sakura Frp（国内速度快，推荐，已实战验证）

1. **注册账号**：打开 https://www.natfrp.com ，注册并完成实名认证（身份证审核约数小时，提前一天办理）。
2. **下载客户端**：官网下载 SakuraFrpLauncher.exe（Windows 启动器），解压后双击运行，用账号登录。
3. **创建隧道**：
   - 左侧点击「隧道」→「创建隧道」
   - 隧道类型：**`Web`**（不要选 TCP，Web 类型可启用自动 HTTPS 获得干净的 https 域名）
   - 服务器节点：选一个**国内节点**（节点列表有延迟数据，选绿色快的）
   - 本地地址：`127.0.0.1`（隧道客户端与后端同机，走回环直达）
   - 本地端口：`8001`
   - **打开「自动 HTTPS」开关**（实名用户可用，自动签发证书）
   - 名称随意，如 `ai-interview-demo`
4. **启动隧道**：点击隧道右侧的开关，等状态变为「运行中」；自动 HTTPS 证书即时签发，若首次访问报证书错误，等 1~2 分钟再试。
5. **获取公网地址**：隧道详情中的访问地址，形如 `https://xxx.natfrp.cloud`（自动 HTTPS 的 Web 隧道）。
6. **访问协议必须是 https**：Sakura Frp 机房合规要求会拦截 `http://` 明文访问（返回 501），手机浏览器不会自动跳转，发地址时一定发 https 开头的完整地址。
7. **验证**：手机关 WiFi 用流量访问 `https://xxx.natfrp.cloud/api/v1/health`，能返回 JSON 即打通。

> 注意：免费版隧道地址可能定期更换，演示当天提前 20 分钟启动隧道并确认地址。

---

## 方案二：NatApp（免费流量，简单）

1. **注册**：打开 https://natapp.cn ，注册账号。
2. **实名认证**：个人中心完成实名认证（免费隧道的必要条件）。
3. **购买免费隧道**：隧道市场 → 购买「免费隧道」（每日可领流量）。
4. **配置隧道**：
   - 隧道类型：`TCP`
   - 本地端口：`8001`
   - 协议：http
5. **下载客户端**：https://natapp.cn/#download 下载 Windows 客户端 natapp.exe。
6. **获取 authtoken**：个人中心 → 我的隧道 → 复制 `authtoken`。
7. **启动隧道**：在命令行执行（把 token 换成你的）：
   ```bat
   natapp.exe -authtoken=你的authtoken
   ```
8. **获取公网地址**：启动后终端会打印：
   ```
   Tunnel Status   online
   Forwarding      http://xxxxxx.natappfree.cc -> 127.0.0.1:8001
   ```
   其中 `http://xxxxxx.natappfree.cc` 就是公网访问地址。
9. **演示**：手机访问该地址即可。

> 注意：免费版 NatApp 首次访问会先显示 NatApp 的提示页，点击「继续访问」进入。

---

## 常见问题

| 问题 | 处理 |
| :--- | :--- |
| 公网打不开，本机正常 | 确认隧道状态为「运行中/online」，且本地端口填的是 8001 |
| **501 Not Implemented（#52）** | 用 `http://` 访问了 Web 隧道 → 改用 **`https://`** 访问；若提示"已启用自动 HTTPS"说明配置成功，仅差把地址换成 https |
| 页面打开但接口 404/报错 | 接口路径为 `/api/v1/...`，确认拼写；公网地址后不用再加端口 |
| 提示 CORS 错误 | 本项目已配置 `*` 通配，若仍报错检查是否访问了旧地址 |
| 免费隧道限速/限流量 | 演示前清空浏览器缓存，语音文件控制在 5MB 内；可切换 Sakura Frp 备用节点 |
| 校园网封隧道端口 | 换 Sakura Frp 的 Web 类型隧道（走 80/443 端口，一般可通） |

## Tailscale 虚拟组网（异地联调，当前在用）

组员不在同一个 WiFi 时，用 Tailscale 把各自的机器拉进一张虚拟内网（免费、私有、不暴露公网）。
前端连后端、后端连对话层引擎都走它，不需要公网穿透。

### 每台机器要做的

1. 装 Tailscale（官网下载，Windows 版一路下一步），用**同一个账号**登录、加入同一个 tailnet。
2. 查地址：

   ```powershell
   tailscale ip -4        # 只取 IPv4，形如 100.x.y.z
   tailscale status       # 完整节点列表：谁在线、各自的地址
   ```

3. 后端这台照常启动 `start.bat`——指引里会自动打印 Tailscale 地址（在线时才打这一行）。

### ⚠️ 校园网会拦 Tailscale

2026-09-29 实测：校园网出口对 Tailscale 的控制服务器连接做了阻断——**TCP 能连上，一进 TLS 就被重置**
（`An existing connection was forcibly closed by the remote host`），客户端一直停在 `NeedsLogin`。
**用手机热点登录一次**即可绕过；登录成功后切回校园网，节点之间往往还能靠缓存状态与 DERP 中继维持
（DERP 是另一组地址，未必也在被拦范围内）。

排查时已排除本机原因：DNS 解析正常（`192.200.0.x` 确实是 Tailscale 自有地址段）、系统无代理、
1472 字节不分片能通（非 MTU 问题）、未见安全管控软件。

### 联调地址

| 用途 | 地址 |
| :--- | :--- |
| 后端接口（前端联调用这个） | `http://<后端那台的Tailscale地址>:8001` |
| 演示前端（若 backend/start.bat 也开着） | `http://<后端那台的Tailscale地址>:5273` |
| 对话层引擎（引擎跑在别人机器上时） | `http://<引擎那台的Tailscale地址>:8005` |

后端把引擎指到别人机器时，在 `backend/.env` 里写：

```
DIALOGUE_ENGINE=a11
DIALOGUE_ENGINE_URL=http://<引擎那台的Tailscale地址>:8005
```

`start.py` 看到引擎地址是远端，就**不会再拉起本地那一份**——本地引擎没人用，
却会占住 8005、吃一份内存，全功能档下还要预热评分器。

### 验证

```powershell
curl http://<后端地址>:8001/api/v1/health     # 期望 code=0 且 status=healthy
curl http://<引擎地址>:8005/health            # 期望 status=ok、scorer_ready=true、llm_configured=true
```

### 连不上时按顺序查

| 现象 | 检查 |
| :--- | :--- |
| 对方 Tailscale 地址 ping 不通 | 两台是否登录了**同一个** tailnet（`tailscale status` 里要能看到对方）；对方是否在线 |
| ping 通但 8001 连不上 | 对端 `start.bat` 是否在跑；**Windows 防火墙**是否放行（见下） |
| 8005 连不上 | 引擎那台的 `FRAMEWORK_HOST` 若被设成 `127.0.0.1`，就只有它本机可达（代码默认是 `0.0.0.0`）；防火墙同理 |
| 面试接口返 503 | 引擎那台不在线或没就绪——`curl <引擎地址>/health` 看 `scorer_ready` 与 `llm_configured` |

放行防火墙（**管理员** PowerShell，在后端/引擎那台上执行）：

```powershell
netsh advfirewall firewall add rule name="AI-Interview-8001" dir=in action=allow `
  protocol=TCP localport=8001 remoteip=100.64.0.0/10
```

⚠️ **为什么必须单独放行**：Windows 把 Tailscale 网卡归为「**专用网络**」(Private)，
而 Python 首次监听时自动创建的放行规则挂在「**公用**」(Public) 上，两者互不通用——
所以 tailnet 里的机器默认连不进来。**本机自测发现不了这件事**：本机访问自己的 Tailscale
地址走的是回环，不经过入站检查，看起来一切正常，等到队友来连才暴露。

查自己机器上的归类（`Tailscale` 那行的 `NetworkCategory`）：

```powershell
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
```

⚠️ **`remoteip=100.64.0.0/10` 不能省**——那是 Tailscale 的地址段，只放 tailnet 内的机器进来；
省掉它就成了「对所有网络（含公网）放开 8001 入站」，不要为了省事那么写。
撤销规则：`netsh advfirewall firewall delete rule name="AI-Interview-8001"`。
引擎自己跑在本机时，8005 同理（把端口换掉即可）。

## 局域网演示（同一 WiFi，无需穿透）

同学/评委与笔记本连同一 WiFi 时，直接访问（start.bat 启动后的指引里也会打印）：

| 用途 | 地址 |
| :--- | :--- |
| 演示前端（完整功能页面） | `http://<你电脑的局域网IP>:5273` |
| Swagger 接口文档 | `http://<你电脑的局域网IP>:8001/docs` |

查看本机 IP：`ipconfig` 中「无线局域网适配器 WLAN」的 IPv4 地址（如 192.168.x.x），
start.py 启动指引里会自动探测并打印。
> 同端口挂载（前端拷入 `backend/static/`）后，一个 `:8001` 地址即可覆盖页面 + 接口。
