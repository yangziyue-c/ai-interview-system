/* ============================================================
 * 页面视图：登录注册 / 岗位大厅 / 岗位详情 / 面试对话室 / 报告 / 个人中心
 *
 * 每个视图 = { render(ctx), mount(ctx) }
 *   render：返回 HTML 字符串（可 async 拉数据）
 *   mount：DOM 插入后绑定事件 / 绘制图表
 * 全局状态挂 window.state（见 app.js）
 * ============================================================ */

const Views = {};

/* ---------- 工具函数 ---------- */
const Helpers = {
  /** HTML 转义，防止用户输入/题库文本注入 */
  esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  },
  /** ISO 时间 → 2026-09-06 10:30 */
  fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  },
  /** ISO 时间 → 09-06 */
  fmtShort(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  },
  /** 岗位 code → 中文名（找不到时原样返回） */
  posName(code) {
    const p = (state.positions || []).find((x) => x.code === code);
    return p ? p.name : code;
  },
  empty(text, icon) {
    return `<div class="empty"><div class="big">${icon || "🗒️"}</div>${this.esc(text)}</div>`;
  },
  /** 单条聊天消息 HTML（render 初始渲染与 appendMsg 动态追加共用） */
  msgHtml(m) {
    return `
      <div class="msg ${m.role}">
        <div class="avatar">${m.role === "ai" ? "🤖" : "🙋"}</div>
        <div>
          <div class="bubble">${this.esc(m.text)}</div>
          ${m.audio_url ? `<audio controls preload="none" src="${this.esc(fileUrl(m.audio_url))}"></audio>` : ""}
          ${m.role === "ai" ? `<div class="qa-round">第 ${m.round} 题</div>` : ""}
        </div>
      </div>`;
  },
  /** 岗位列表缓存加载（大厅/个人中心/详情共用，失败抛给调用方处理） */
  async ensurePositions() {
    if (!state.positions) state.positions = await Api.positions();
    return state.positions;
  },
};

/* ============================================================
 * 1. 登录 / 注册
 * ============================================================ */
Views.auth = {
  async render() {
    return `
    <div class="auth-page">
      <div class="auth-logo">
        <div class="logo-icon">🎤</div>
        <h1>AI 模拟面试</h1>
        <p>${App.TOTAL_ROUNDS} 轮追问 · 5 维评分 · 专属成长报告</p>
      </div>
      <div class="auth-card">
        <div class="auth-tabs">
          <button id="auth-tab-login" class="active">登录</button>
          <button id="auth-tab-register">注册</button>
        </div>

        <!-- 登录表单 -->
        <form id="login-form">
          <div class="field"><label>用户名</label>
            <input class="input" name="username" placeholder="请输入用户名" autocomplete="username"></div>
          <div class="field"><label>密码</label>
            <input class="input" type="password" name="password" placeholder="请输入密码" autocomplete="current-password"></div>
          <button class="btn btn-primary btn-block" type="submit">登 录</button>
        </form>

        <!-- 注册表单 -->
        <form id="register-form" class="hidden">
          <div class="field"><label>用户名（登录账号，3~32 位）</label>
            <input class="input" name="username" placeholder="如 zhangsan" autocomplete="username"></div>
          <div class="field"><label>密码（至少 6 位）</label>
            <input class="input" type="password" name="password" placeholder="至少 6 位" autocomplete="new-password"></div>
          <div class="field"><label>昵称（选填，默认同用户名）</label>
            <input class="input" name="nickname" placeholder="如 张三"></div>
          <div class="field"><label>学号（选填）</label>
            <input class="input" name="student_id" placeholder="如 20260001"></div>
          <button class="btn btn-primary btn-block" type="submit">注册并登录</button>
        </form>

        <div class="auth-tip">新用户请先注册，系统无内置账号</div>
      </div>
    </div>`;
  },

  mount() {
    // 登录/注册 tab 切换
    const tabLogin = document.getElementById("auth-tab-login");
    const tabRegister = document.getElementById("auth-tab-register");
    const loginForm = document.getElementById("login-form");
    const registerForm = document.getElementById("register-form");
    const switchTab = (isLogin) => {
      tabLogin.classList.toggle("active", isLogin);
      tabRegister.classList.toggle("active", !isLogin);
      loginForm.classList.toggle("hidden", !isLogin);
      registerForm.classList.toggle("hidden", isLogin);
    };
    tabLogin.addEventListener("click", () => switchTab(true));
    tabRegister.addEventListener("click", () => switchTab(false));

    /** 登录/注册成功后的统一收尾：存登录态 → 提示 → 进入大厅 */
    const afterAuth = (data, okMsg) => {
      setToken(data.access_token);
      state.user = data.user;
      localStorage.setItem("user", JSON.stringify(data.user));
      App.toast(okMsg, "ok");
      App.goto("#/hall");
    };

    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(loginForm);
      const btn = loginForm.querySelector("button");
      btn.disabled = true;
      try {
        const data = await Api.login({
          username: fd.get("username").trim(),
          password: fd.get("password"),
        });
        afterAuth(data, "登录成功");
      } catch (err) {
        App.toast(err.message, "err");
      } finally {
        btn.disabled = false;
      }
    });

    registerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(registerForm);
      const username = fd.get("username").trim();
      const password = fd.get("password");
      // 与后端 RegisterRequest 校验规则一致
      if (username.length < 3) return App.toast("用户名至少 3 位", "err");
      if (password.length < 6) return App.toast("密码至少 6 位", "err");
      const btn = registerForm.querySelector("button");
      btn.disabled = true;
      try {
        const data = await Api.register({
          username,
          password,
          nickname: fd.get("nickname").trim() || undefined,
          student_id: fd.get("student_id").trim() || undefined,
          // 注：GET /positions 需登录态，注册时无法拉取岗位列表，
          // target_position 使用后端默认值 backend，开始面试时再选择岗位
        });
        afterAuth(data, "注册成功，欢迎加入！");
      } catch (err) {
        App.toast(err.message, "err");
      } finally {
        btn.disabled = false;
      }
    });
  },
};

/* ============================================================
 * 2. 岗位大厅
 * ============================================================ */
Views.hall = {
  async render() {
    try {
      await Helpers.ensurePositions();
    } catch (err) {
      return Helpers.empty("岗位列表加载失败：" + err.message, "⚠️");
    }
    const user = state.user || {};
    const cards = state.positions
      .map(
        (p) => `
      <div class="pos-card" data-code="${Helpers.esc(p.code)}">
        <div class="pos-name">${Helpers.esc(p.name)}</div>
        <div class="pos-desc">${Helpers.esc(p.description || "")}</div>
        <div class="pos-tags">
          ${(p.tech_stack || []).slice(0, 4).map((t) => `<span class="tag">${Helpers.esc(t)}</span>`).join("")}
        </div>
      </div>`
      )
      .join("");
    return `
      <div class="page-title">你好，${Helpers.esc(user.nickname || user.username || "")} 👋</div>
      <div class="page-sub">选择一个岗位，开始你的模拟面试之旅</div>
      ${cards || Helpers.empty("暂无开放岗位", "🏢")}`;
  },

  mount() {
    document.querySelectorAll(".pos-card").forEach((card) => {
      card.addEventListener("click", () => App.goto("#/position/" + card.dataset.code));
    });
  },
};

/* ============================================================
 * 3. 岗位详情
 * ============================================================ */
Views.position = {
  async render({ code }) {
    // 深链/刷新直接进入时岗位列表可能尚未加载，先确保缓存
    try {
      await Helpers.ensurePositions();
    } catch (err) {
      return Helpers.empty("岗位列表加载失败：" + err.message, "⚠️");
    }
    const p = (state.positions || []).find((x) => x.code === code);
    if (!p) {
      // 返回空串跳过 mount（页面无元素可绑），由路由跳转兜底
      App.toast("岗位不存在", "err");
      App.goto("#/hall");
      return "";
    }
    return `
      <div class="topbar">
        <button class="back" data-back>←</button>
        <span>岗位详情</span>
      </div>
      <div class="detail-head">
        <h2>${Helpers.esc(p.name)}</h2>
        <p>${Helpers.esc(p.description || "")}</p>
      </div>
      <div class="card detail-section">
        <h3>🛠️ 技术栈要求</h3>
        <div class="pos-tags">${(p.tech_stack || []).map((t) => `<span class="tag">${Helpers.esc(t)}</span>`).join("")}</div>
      </div>
      <div class="card detail-section">
        <h3>🎯 面试考察重点</h3>
        ${(p.focus || []).map((f) => `<div class="list-item"><span class="mark">•</span><span>${Helpers.esc(f)}</span></div>`).join("")}
      </div>
      <div class="start-bar">
        <button class="btn btn-primary btn-block" id="btn-start">🚀 开始面试</button>
        <div class="auth-tip">共 ${App.TOTAL_ROUNDS} 轮：1 道开场题 + ${App.TOTAL_ROUNDS - 1} 道追问，随时可提前结束</div>
      </div>`;
  },

  mount({ code }) {
    document.querySelector('[data-back]').addEventListener("click", () => history.back());
    document.getElementById("btn-start").addEventListener("click", async () => {
      const btn = document.getElementById("btn-start");
      btn.disabled = true;
      btn.textContent = "正在创建面试…";
      try {
        const data = await Api.startInterview(code);
        // 保存会话并进入对话室（消息列表只含开场题）
        state.interview = data.interview;
        state.messages = [{ role: "ai", text: data.question, round: 1 }];
        App.goto("#/interview/" + data.interview.id);
      } catch (err) {
        if (err.code === 40900) {
          // 已有一场进行中的面试 → 从历史列表找到它并引导继续
          const ongoing = await App.findOngoing();
          if (ongoing && confirm("你有一场进行中的面试（" + Helpers.posName(ongoing.position) + " 第 " + ongoing.current_round + " 题）。\n是否前往继续？")) {
            App.goto("#/interview/" + ongoing.id);
            return;
          }
        }
        App.toast(err.message, "err");
      } finally {
        btn.disabled = false;
        btn.textContent = "🚀 开始面试";
      }
    });
  },
};

/* ============================================================
 * 4. 面试对话室（核心）
 * ============================================================ */
Views.interview = {
  async render({ id }) {
    // 已结束的面试不允许再进对话室（提交必撞 409），直接引导看报告
    if (state.interview && state.interview.id === Number(id) && state.interview.status === "finished") {
      App.goto("#/report/" + id);
      return "";
    }
    // 每次进入都从详情接口同步会话：内存缓存可能落后于服务端（如上一视图的
    // 迟响应已被丢弃、轮次已推进），按 id 短路会把用户留在陈旧的"第 N 题"上
    try {
      const detail = await Api.interviewDetail(id);
      if (detail.status === "finished") {
        App.goto("#/report/" + id);
        return "";
      }
      state.interview = detail;
      state.messages = [];
      (detail.qa_records || [])
        .slice()
        .sort((a, b) => a.round - b.round)
        .forEach((qa) => {
          state.messages.push({ role: "ai", text: qa.question, round: qa.round });
          if (qa.answer) state.messages.push({ role: "user", text: qa.answer, round: qa.round, audio_url: qa.audio_url });
        });
    } catch (err) {
      App.toast(err.message, "err");
      App.goto("#/profile");
      return "";
    }

    const iv = state.interview;
    const total = App.TOTAL_ROUNDS;
    const canVoice = Voice.supported.stt || Voice.supported.rec;

    return `
    <div class="chat-room">
      <div class="chat-top">
        <button class="back" data-back>←</button>
        <h3>${Helpers.esc(Helpers.posName(iv.position))}</h3>
        <span class="round-pill" id="round-pill">第 ${iv.current_round}/${total} 题</span>
        <button class="top-btn" id="btn-finish">结束面试</button>
      </div>

      <div class="chat-list" id="chat-list">
        ${state.messages.map((m) => Helpers.msgHtml(m)).join("")}
      </div>

      ${canVoice ? `<div class="chat-voice-tip">🎙️ 按住话筒说话，松开自动转写并录音；也可直接输入文字</div>` : ""}

      <div class="chat-input-bar">
        ${canVoice ? `<button class="icon-btn voice" id="btn-voice" title="按住说话">🎙️</button>` : ""}
        <textarea id="answer-input" rows="1" placeholder="输入你的回答…"></textarea>
        <button class="icon-btn send" id="btn-send" title="发送">➤</button>
      </div>
    </div>`;
  },

  mount({ id }) {
    const list = document.getElementById("chat-list");
    const input = document.getElementById("answer-input");
    const btnSend = document.getElementById("btn-send");
    const pill = document.getElementById("round-pill");
    const sessionId = Number(id); // 会话身份：慢响应返回时校验是否仍在本场面试
    let busy = false; // 提交答案期间禁发

    const scrollBottom = () => (list.scrollTop = list.scrollHeight);
    scrollBottom();

    document.querySelector('[data-back]').addEventListener("click", () => App.goto("#/hall"));

    // 自动增高输入框
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 110) + "px";
    });

    /** 追加"面试官思考中"气泡，返回移除函数 */
    const showThinking = () => {
      const el = document.createElement("div");
      el.className = "msg ai thinking";
      el.innerHTML = `
        <div class="avatar">🤖</div>
        <div class="bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>`;
      list.appendChild(el);
      scrollBottom();
      return () => el.remove();
    };

    /** 追加消息：同步进 state.messages 并渲染到聊天区 */
    const appendMsg = (m) => {
      state.messages.push(m);
      const el = document.createElement("div");
      el.innerHTML = Helpers.msgHtml(m);
      list.appendChild(el.firstElementChild);
      scrollBottom();
    };

    /** 提交答案：转写文本 + 录音上传 + 获取下一题 */
    const submit = async () => {
      if (busy) return;

      // 先停录音并等其落盘，再读输入框：
      // ① 按住话筒中点发送 → stop 的 flush 文本写入输入框后才能被本次提交取到
      // ② 松开后立即发送 → 等 onstop 落盘，pending 归属本条答案而非下一条
      if (Voice._recording) Voice.stop();
      if (Voice._stopPromise) await Voice._stopPromise;

      const answer = input.value.trim();
      if (!answer) return App.toast("请先输入或说出你的回答", "err");

      busy = true;
      btnSend.disabled = true;
      const submitRound = state.interview.current_round; // 提交发起时捕获轮次，迟响应乱序时标签不错位
      const removeThinking = showThinking();

      let audioUrl = null;
      if (Voice.pending) {
        try {
          audioUrl = await Voice.upload();
          audioUrl && App.toast("录音已上传", "ok");
        } catch (err) {
          App.toast("录音上传失败，将仅提交文本：" + err.message, "err");
        }
      }

      try {
        const data = await Api.submitAnswer(id, answer, audioUrl);
        // 慢响应期间用户可能已离开本场面试：本视图 DOM 已被替换（list 脱离文档）即丢弃迟到响应
        if (!document.contains(list)) return;
        removeThinking();
        appendMsg({ role: "user", text: answer, round: submitRound, audio_url: audioUrl });
        input.value = "";
        input.style.height = "auto";

        if (data.finished) {
          // 轮次全部完成，自动生成报告
          state.interview = data.interview;
          state.currentReport = data.report;
          state.reports[id] = data.report;
          state.currentReportPos = null; // 本场报告以 interview.position 为准
          App.toast("面试已完成，正在查看报告 🎉", "ok");
          App.goto("#/report/" + id);
        } else {
          state.interview = data.interview;
          appendMsg({ role: "ai", text: data.next_question, round: data.interview.current_round });
          pill.textContent = `第 ${data.interview.current_round}/${App.TOTAL_ROUNDS} 题`;
        }
      } catch (err) {
        if (!document.contains(list)) return;
        removeThinking();
        if (err.code === 40900) {
          // 面试已被结束（如其他页面操作）→ 跳个人中心
          App.toast(err.message, "err");
          App.goto("#/profile");
        } else {
          App.toast(err.message, "err");
        }
      } finally {
        busy = false;
        btnSend.disabled = false;
      }
    };

    btnSend.addEventListener("click", submit);
    input.addEventListener("keydown", (e) => {
      // isComposing/keyCode 229：中文输入法候选确认的 Enter 不触发提交
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
        e.preventDefault();
        submit();
      }
    });

    // 结束面试
    document.getElementById("btn-finish").addEventListener("click", async () => {
      if (busy) return;
      // 后端要求至少一条有效回答才能生成报告（否则 400 无法结束）
      if (!state.messages.some((m) => m.role === "user")) {
        return App.toast("请至少回答一题后再结束面试", "err");
      }
      if (!confirm("确定结束当前面试吗？\n将基于已提交的回答生成评估报告。")) return;
      busy = true;
      try {
        const data = await Api.finishInterview(id);
        if (!document.contains(list)) return;
        state.interview = data.interview;
        state.currentReportPos = null; // 本场报告以 interview.position 为准
        App.toast("面试已结束，正在生成报告", "ok");
        App.goto("#/report/" + id);
      } catch (err) {
        App.toast(err.message, "err");
        busy = false;
      }
    });

    // 语音：按住说话，松开转写 + 录音
    const btnVoice = document.getElementById("btn-voice");
    if (btnVoice) {
      Voice.onTranscript = (text) => {
        const cur = input.value.trim();
        input.value = cur ? cur + " " + text : text;
        input.dispatchEvent(new Event("input"));
      };
      Voice.onStateChange = (rec) => btnVoice.classList.toggle("recording", rec);
      Voice.onError = (msg) => App.toast(msg, "err");

      const press = (e) => {
        e.preventDefault(); // 阻止长按弹出菜单
        if (busy) return App.toast("面试官正在出题，请稍候", "err");
        Voice.start();
      };
      const release = () => Voice.stop();
      btnVoice.addEventListener("mousedown", press);
      btnVoice.addEventListener("touchstart", press, { passive: false });
      btnVoice.addEventListener("mouseup", release);
      btnVoice.addEventListener("mouseleave", release);
      btnVoice.addEventListener("touchend", release);
    }
  },
};

/* ============================================================
 * 5. 报告页
 * ============================================================ */
Views.report = {
  async render({ id }) {
    // 报告生成后不可变，按 id 缓存避免反复请求（从面试完成跳转时已有现成数据）
    let report = state.reports[id];
    if (!report) {
      try {
        report = await Api.report(id);
        state.reports[id] = report;
      } catch (err) {
        App.toast(err.message, "err");
        App.goto("#/profile");
        return "";
      }
    }
    state.currentReport = report;

    const listHtml = (title, items, mark, color) =>
      items && items.length
        ? `<div class="card detail-section"><div class="sec-title">${title}</div>
           ${items.map((s) => `<div class="list-item"><span class="mark" style="color:${color}">${mark}</span><span>${Helpers.esc(s)}</span></div>`).join("")}</div>`
        : "";

    return `
      <div class="topbar">
        <button class="back" data-back>←</button>
        <span>面试报告</span>
      </div>
      <div class="score-hero">
        <div class="score-num">${Number(report.total_score).toFixed(1)}</div>
        <div class="score-label">综合得分 · ${Helpers.esc(Helpers.posName(state.currentReportPos || state.interview?.position || ""))}</div>
      </div>
      <div class="radar-wrap">
        <div class="sec-title">📊 五维能力雷达</div>
        <canvas id="radar-canvas"></canvas>
      </div>
      <div class="card detail-section">
        <div class="sec-title">💬 综合评语</div>
        <div class="summary-text">${Helpers.esc(report.summary || "暂无评语")}</div>
      </div>
      ${listHtml("👍 你的优势", report.strengths, "✔", "#1fbf75")}
      ${listHtml("📌 待改进之处", report.weaknesses, "!", "#f5a623")}
      ${listHtml("📚 改进建议", report.suggestions, "»", "#4f6ef7")}
      <div class="card detail-section">
        <div class="sec-title">📈 能力成长曲线</div>
        <div id="growth-box"></div>
      </div>`;
  },

  mount({ id }) {
    document.querySelector('[data-back]').addEventListener("click", () => App.goto("#/profile"));

    // 雷达图
    const report = state.currentReport;
    Charts.drawRadar(document.getElementById("radar-canvas"), [
      { label: "技术水平", value: report.tech_score },
      { label: "逻辑思维", value: report.logic_score },
      { label: "沟通表达", value: report.expression_score },
      { label: "应变能力", value: report.adaptability_score },
      { label: "岗位匹配度", value: report.match_score },
    ], { w: 300, h: 260 });

    // 成长曲线（历史所有已结束面试，按时间升序）
    const growthBox = document.getElementById("growth-box");
    Api.growth()
      .then((points) => {
        if (!document.contains(growthBox)) return; // 已离开报告页，丢弃迟到响应
        if (!points || points.length < 2) {
          growthBox.innerHTML = `<div class="growth-empty">完成第二场面试后，这里会展示你的成长曲线 📈</div>`;
          return;
        }
        growthBox.innerHTML = `<canvas id="growth-canvas"></canvas>`;
        Charts.drawGrowth(
          document.getElementById("growth-canvas"),
          points.map((p) => ({ label: Helpers.fmtShort(p.finished_at), value: p.total_score })),
          { w: 300, h: 180 }
        );
      })
      .catch((err) => {
        if (!document.contains(growthBox)) return;
        growthBox.innerHTML = `<div class="growth-empty">成长曲线加载失败：${Helpers.esc(err.message)}</div>`;
      });
  },
};

/* ============================================================
 * 6. 个人中心
 * ============================================================ */
Views.profile = {
  async render() {
    const user = state.user || (state.user = await Api.me());
    try {
      await Helpers.ensurePositions();
    } catch (err) {
      /* 岗位名兜底显示 code */
    }

    // 历史列表与最近建议互不依赖，并行请求
    let items, latest;
    try {
      [items, latest] = await Promise.all([Api.listInterviews(), Api.latestSuggestion()]);
    } catch (err) {
      App.toast(err.message, "err");
      items = [];
      latest = null;
    }
    const listHtml = items.length
      ? items
          .map((iv) => {
            const score = iv.total_score;
            const isOngoing = iv.status === "in_progress";
            return `
            <div class="history-item" data-id="${iv.id}" data-status="${iv.status}" data-pos="${Helpers.esc(iv.position)}">
              <div class="h-pos">
                ${Helpers.esc(Helpers.posName(iv.position))}
                <div class="h-sub">
                  ${Helpers.esc(Helpers.fmtDate(iv.created_at))}
                  ${isOngoing ? `· <span class="status-pill ongoing">进行中 第 ${iv.current_round} 题</span>` : `<span class="status-pill finished">已完成</span>`}
                </div>
              </div>
              ${isOngoing ? `<div class="h-score gray">继续 ></div>` : `<div class="h-score">${score != null ? Number(score).toFixed(1) : "—"}</div>`}
            </div>`;
          })
          .join("")
      : Helpers.empty("还没有面试记录，去大厅开始第一场吧", "🗒️");

    const suggestHtml = `<div class="card detail-section">
      <div class="sec-title">💡 最近一次改进建议</div>
      ${
        latest
          ? `<div class="h-sub" style="margin-bottom:8px">
              ${Helpers.esc(Helpers.posName(latest.position))} · ${Helpers.esc(Helpers.fmtDate(latest.finished_at))} · 得分 ${Number(latest.total_score).toFixed(1)}
            </div>
            ${(latest.suggestions || []).map((s) => `<div class="suggest-item">${Helpers.esc(s)}</div>`).join("")}`
          : `<div class="growth-empty">暂无建议，快去完成一场面试吧！</div>`
      }
    </div>`;

    const initial = (user.nickname || user.username || "?").charAt(0).toUpperCase();
    return `
      <div class="profile-head">
        <div class="profile-avatar">${Helpers.esc(initial)}</div>
        <div>
          <div class="name">${Helpers.esc(user.nickname || user.username)}</div>
          <div class="meta">学号：${Helpers.esc(user.student_id || "未填写")}</div>
          <div class="meta">目标岗位：${Helpers.esc(Helpers.posName(user.target_position))}</div>
        </div>
      </div>
      <div class="card detail-section">
        <div class="sec-title">📋 我的面试记录</div>
        ${listHtml}
      </div>
      ${suggestHtml}
      <div class="logout-btn">
        <button class="btn btn-ghost" id="btn-logout">退出登录</button>
      </div>`;
  },

  mount() {
    document.querySelectorAll(".history-item").forEach((item) => {
      item.addEventListener("click", () => {
        const id = item.dataset.id;
        if (item.dataset.status === "in_progress") {
          App.goto("#/interview/" + id);
        } else {
          // 报告接口不含岗位字段，先记下岗位 code 供报告页展示
          state.currentReportPos = item.dataset.pos;
          App.goto("#/report/" + id);
        }
      });
    });
    document.getElementById("btn-logout").addEventListener("click", () => {
      if (!confirm("确定退出登录吗？")) return;
      clearToken();
      // 全量清空会话状态（与 401 踢出共用同一函数），防止换账号后残留上一账号数据
      App.resetState();
      App.goto("#/login");
    });
  },
};
