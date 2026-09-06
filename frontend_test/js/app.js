/* ============================================================
 * 主逻辑：全局状态 / hash 路由 / 登录守卫 / 底部 Tab / Toast
 * ============================================================ */

/* ---------- 全局状态（views.js 各视图共用） ---------- */
window.state = {
  user: JSON.parse(localStorage.getItem("user") || "null"),
  positions: null, // 岗位列表缓存（数据来自 GET /positions，不硬编码）
  interview: null, // 当前面试会话（InterviewOut）
  messages: [], // 对话室消息 [{role: "ai"|"user", text, round, audio_url?}]
  currentReport: null, // 当前查看的报告
  reports: {}, // 报告缓存 {interview_id: ReportOut}（报告生成后不可变）
  currentReportPos: null, // 从个人中心进入报告页时携带的岗位 code
};

/* ---------- 应用入口 ---------- */
window.App = {
  /** 与后端 config.total_rounds 一致：1 开场题 + 6 追问 */
  TOTAL_ROUNDS: 7,

  /* ---------- 轻提示 ---------- */
  toast(msg, type) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = type || "";
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
  },

  /* ---------- 路由跳转 ---------- */
  goto(hash) {
    if (location.hash === hash) this.render();
    else location.hash = hash;
  },

  /* ---------- token 失效兜底（api.js 抛出 40100 时回调） ---------- */
  onUnauthorized() {
    this.resetState();
    this.toast("登录已过期，请重新登录", "err");
    this.goto("#/login");
  },

  /* ---------- 清空全部会话状态（401 踢出与主动退出登录共用，字段集必须一致） ---------- */
  resetState() {
    state.user = null;
    state.positions = null;
    state.interview = null;
    state.messages = [];
    state.currentReport = null;
    state.reports = {};
    state.currentReportPos = null;
  },

  /* ---------- 从历史列表找进行中的面试（冲突引导用） ---------- */
  async findOngoing() {
    try {
      const items = await Api.listInterviews();
      return items.find((i) => i.status === "in_progress") || null;
    } catch (e) {
      return null;
    }
  },

  /* ---------- 主渲染：hash 路由 → 视图 ---------- */
  async render() {
    const raw = location.hash.replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean);
    const name = parts[0] || "";
    const id = parts[1];

    // 登录守卫：未登录一律回登录页；已登录访问根路径/登录页 → 大厅
    let route = { name, id };
    if (!getToken()) route = { name: "login", id: null };
    else if (!name || name === "login") route = { name: "hall", id: null };

    const table = {
      login: Views.auth,
      hall: Views.hall,
      position: Views.position,
      interview: Views.interview,
      report: Views.report,
      profile: Views.profile,
    };
    const view = table[route.name] || Views.hall;

    // 离开对话室时停止录音、释放麦克风，并丢弃未发送的录音（防止错配到下一条答案）
    if (route.name !== "interview" && Voice._recording) Voice.stop();
    if (route.name !== "interview") Voice.pending = null;

    // 渲染视图（render 可能异步拉数据；返回空串表示已在内部跳转，跳过 mount）
    const viewEl = document.getElementById("view");
    // 渲染代际：慢视图返回时若路由已切换，丢弃过期结果。
    // 注意必须显式从 0 起计数——++undefined 得 NaN，NaN !== NaN 恒真会把每次渲染都丢弃（白屏）
    const seq = (this._renderSeq = (this._renderSeq || 0) + 1);
    let html;
    try {
      html = await view.render({ code: id, id });
    } catch (err) {
      // 视图渲染抛错：仅 40100 按登录失效处理；500/网络抖动等其他错误不清登录态，
      // 提示后回大厅（若当前已在大厅则停留在原地，由下一次导航重试）
      this.toast("页面加载失败：" + err.message, "err");
      if (err.code === 40100) {
        this.resetState();
        this.goto("#/login");
      } else if (route.name !== "hall") {
        this.goto("#/hall");
      }
      return;
    }
    if (seq !== this._renderSeq) return; // 期间已发生新的渲染，本次作废
    viewEl.innerHTML = html;
    if (html) view.mount && view.mount({ code: id, id });

    // 底部 Tab 栏：仅大厅/个人中心显示；全屏页（对话室/登录等）收起
    const showTab = route.name === "hall" || route.name === "profile";
    document.getElementById("tabbar").classList.toggle("hidden", !showTab);
    viewEl.classList.toggle("no-tab", !showTab);
    if (showTab) {
      document.querySelectorAll(".tab-item").forEach((b) => {
        b.classList.toggle("active", b.dataset.tab === route.name);
      });
    }
    window.scrollTo(0, 0);
  },
};

/* ---------- 事件绑定与启动 ---------- */
window.addEventListener("hashchange", () => App.render());
window.addEventListener("DOMContentLoaded", () => {
  // 底部 Tab 切换
  document.querySelectorAll(".tab-item").forEach((btn) => {
    btn.addEventListener("click", () => App.goto("#/" + btn.dataset.tab));
  });
  // 初始路由：无 hash 时按登录态落位（goto 触发的 hashchange 会渲染，勿重复 render）
  if (!location.hash) App.goto(getToken() ? "#/hall" : "#/login");
  else App.render();
});
