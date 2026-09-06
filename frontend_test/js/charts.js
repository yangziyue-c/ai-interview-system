/* ============================================================
 * 轻量图表：原生 canvas 绘制，无第三方依赖
 *   - 雷达图：报告 5 维评分（技术/逻辑/表达/应变/匹配）
 *   - 成长曲线：历史面试总分折线
 * ============================================================ */

/** 高分屏适配：按设备像素比初始化 canvas 并返回 2D 上下文 */
function setupCanvas(canvas, w, h) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return ctx;
}

const Charts = {
  /**
   * 5 维雷达图
   * @param {HTMLCanvasElement} canvas
   * @param {Array}  items  [{ label, value }]，value 0~100
   * @param {Object} size   { w, h } 逻辑像素尺寸
   */
  drawRadar(canvas, items, size) {
    const { w, h } = size;
    const ctx = setupCanvas(canvas, w, h);

    const cx = w / 2;
    const cy = h / 2;
    const r = Math.min(w, h) / 2 - 34; // 留出标签空间
    const n = items.length;
    const angleOf = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const point = (i, ratio) => ({
      x: cx + r * ratio * Math.cos(angleOf(i)),
      y: cy + r * ratio * Math.sin(angleOf(i)),
    });

    // 网格：5 层同心五边形
    for (let level = 1; level <= 5; level++) {
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const p = point(i, level / 5);
        i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
      }
      ctx.closePath();
      ctx.strokeStyle = level === 5 ? "#c9d2ee" : "#e8ecf8";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // 轴线 + 维度标签
    ctx.font = "12px -apple-system, PingFang SC, Microsoft YaHei, sans-serif";
    ctx.fillStyle = "#5a6378";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (let i = 0; i < n; i++) {
      const outer = point(i, 1);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(outer.x, outer.y);
      ctx.strokeStyle = "#e8ecf8";
      ctx.stroke();
      // 标签放在轴外延
      const label = point(i, 1.32);
      ctx.fillText(items[i].label, label.x, label.y);
    }

    // 数据多边形
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const p = point(i, Math.max(items[i].value, 0) / 100);
      i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(79, 110, 247, 0.18)";
    ctx.fill();
    ctx.strokeStyle = "#4f6ef7";
    ctx.lineWidth = 2;
    ctx.stroke();

    // 数据点 + 分数标注
    for (let i = 0; i < n; i++) {
      const p = point(i, Math.max(items[i].value, 0) / 100);
      ctx.beginPath();
      ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
      ctx.fillStyle = "#4f6ef7";
      ctx.fill();
      const tip = point(i, Math.max(items[i].value, 0) / 100 + 0.16);
      ctx.fillStyle = "#1f2430";
      ctx.font = "bold 11px -apple-system, PingFang SC, Microsoft YaHei, sans-serif";
      ctx.fillText(String(items[i].value), tip.x, tip.y);
    }
  },

  /**
   * 成长曲线（总分折线）
   * @param {HTMLCanvasElement} canvas
   * @param {Array}  points [{ label, value }] 按时间升序
   * @param {Object} size   { w, h }
   */
  drawGrowth(canvas, points, size) {
    const { w, h } = size;
    const ctx = setupCanvas(canvas, w, h);

    const pad = { l: 34, r: 16, t: 18, b: 30 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    const minScore = 0;
    const maxScore = 100;

    const xOf = (i) => pad.l + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
    const yOf = (v) => pad.t + plotH * (1 - (v - minScore) / (maxScore - minScore));

    // 横向网格 + Y 轴刻度（0/50/100）
    ctx.font = "11px -apple-system, PingFang SC, Microsoft YaHei, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    [0, 50, 100].forEach((v) => {
      const y = yOf(v);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(w - pad.r, y);
      ctx.strokeStyle = "#e8ecf8";
      ctx.stroke();
      ctx.fillStyle = "#9aa2b8";
      ctx.fillText(String(v), pad.l - 6, y);
    });

    // X 轴标签（面试日期，只取月-日）
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    points.forEach((p, i) => {
      ctx.fillStyle = "#9aa2b8";
      ctx.fillText(p.label, xOf(i), h - pad.b + 8);
    });

    // 折线
    ctx.beginPath();
    points.forEach((p, i) => {
      i === 0 ? ctx.moveTo(xOf(i), yOf(p.value)) : ctx.lineTo(xOf(i), yOf(p.value));
    });
    ctx.strokeStyle = "#4f6ef7";
    ctx.lineWidth = 2;
    ctx.stroke();

    // 面积渐变填充
    ctx.lineTo(xOf(points.length - 1), pad.t + plotH);
    ctx.lineTo(xOf(0), pad.t + plotH);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + plotH);
    grad.addColorStop(0, "rgba(79, 110, 247, 0.20)");
    grad.addColorStop(1, "rgba(79, 110, 247, 0.02)");
    ctx.fillStyle = grad;
    ctx.fill();

    // 数据点 + 分数
    points.forEach((p, i) => {
      const x = xOf(i);
      const y = yOf(p.value);
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = "#4f6ef7";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, 7, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(79, 110, 247, 0.15)";
      ctx.fill();
      ctx.fillStyle = "#1f2430";
      ctx.font = "bold 12px -apple-system, PingFang SC, Microsoft YaHei, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(String(p.value), x, y - 8);
    });
  },
};
