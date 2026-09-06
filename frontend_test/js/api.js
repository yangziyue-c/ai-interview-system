/* ============================================================
 * API 请求封装：统一鉴权、统一响应 {code, message, data} 解析
 *
 * Base URL 自适应：
 *   - 页面由 8001 同端口（backend/static 挂载/隧道反代）提供 → 相对路径 /api/v1，无跨域
 *   - 页面由静态服务器（5273，见 start.py 一键拉起）提供 → 直连同一主机的 8001（后端 CORS 已全开）
 * ============================================================ */

// API 主机：默认同源相对路径（8001 同端口挂载、隧道/反代等场景都正确）；
// 仅已知的独立开发场景（5173/5273 静态站、file://）才显式指向**同一主机**的 8001——
// 不能硬编码 localhost（局域网设备会请求到自己的本机），协议继承页面（避免 https 下混合内容拦截）
const API_HOST =
  location.port === "5173" || location.port === "5273" || location.protocol === "file:"
    ? (location.protocol.startsWith("http") ? location.protocol : "http:") +
      "//" +
      (location.hostname || "localhost") +
      ":8001"
    : "";
const API_BASE = API_HOST + "/api/v1";

/** 上传接口返回的相对路径（如 /uploads/1_ab3f.mp3）转完整可访问 URL */
function fileUrl(path) {
  if (!path) return "";
  if (/^https?:\/\//.test(path)) return path;
  return API_HOST + path;
}

class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function getToken() {
  return localStorage.getItem("token") || "";
}

function setToken(token) {
  localStorage.setItem("token", token);
}

function clearToken() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
}

/**
 * 发起请求，返回 data 字段
 * @param {string} path   接口路径（相对 /api/v1，如 "/auth/login"）
 * @param {object} opts   { method, body, formData, silent }
 *   body:     自动 JSON 序列化
 *   formData: multipart 上传（FormData 实例）
 */
async function request(path, opts = {}) {
  const headers = {};
  let payload;
  if (opts.formData) {
    payload = opts.formData;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(opts.body);
  }
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  let resp;
  try {
    resp = await fetch(API_BASE + path, {
      method: opts.method || (payload ? "POST" : "GET"),
      headers,
      body: payload,
    });
  } catch (e) {
    // 网络错误（后端未启动等）
    throw new ApiError(-1, "无法连接后端服务，请确认 backend 已启动（8001 端口）");
  }

  let json;
  try {
    json = await resp.json();
  } catch (e) {
    throw new ApiError(-1, "后端响应异常（HTTP " + resp.status + "）");
  }

  if (json.code !== 0) {
    // token 失效：清登录态并回登录页（由 app.js 的 onUnauthorized 兜底处理）。
    // 仅排除登录/注册两个表单接口：其 40100 是"用户名或密码错误"而非登录过期，
    // 误触发会清空登录表单；/auth/me 等其他接口的 40100 仍需走全局登出流程
    const isAuthForm = path === "/auth/login" || path === "/auth/register";
    if (json.code === 40100 && !opts.silent && !isAuthForm) {
      clearToken();
      if (typeof App !== "undefined" && App.onUnauthorized) App.onUnauthorized();
    }
    throw new ApiError(json.code, json.message || "请求失败");
  }
  return json.data;
}

/* ---------- 各业务接口（路径/字段对照 docs/API.md） ---------- */
const Api = {
  // 认证
  register: (data) => request("/auth/register", { body: data }),
  login: (data) => request("/auth/login", { body: data }),
  me: () => request("/auth/me"),

  // 岗位
  positions: () => request("/positions"),

  // 面试
  startInterview: (position) => request("/interviews", { body: { position } }),
  listInterviews: () => request("/interviews"),
  interviewDetail: (id) => request("/interviews/" + id),
  submitAnswer: (id, answer, audioUrl) =>
    request("/interviews/" + id + "/answers", {
      body: { answer, audio_url: audioUrl || null },
    }),
  finishInterview: (id) => request("/interviews/" + id + "/finish", { method: "POST" }),

  // 报告
  report: (id) => request("/reports/" + id),
  latestSuggestion: () => request("/reports/latest"),
  growth: () => request("/reports/growth"),

  // 上传录音（字段名 file）
  uploadAudio: (blob, filename) => {
    const fd = new FormData();
    fd.append("file", blob, filename);
    return request("/uploads/audio", { formData: fd });
  },
};
