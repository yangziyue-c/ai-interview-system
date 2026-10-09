/**
 * 《项目的详细分工及过程》演示稿生成脚本（20 页 · 版式多样化版）。
 *
 * 项目：深镜智聘 · 基于多模态交互与动态知识图谱的计算机岗位 AI 模拟面试与能力提升平台
 * 小队：Alpha 小队
 * 主题：Tech Innovation（电光蓝 0066FF / 霓虹青 00FFFF / 深灰 1E1E1E）
 * 字体：微软雅黑（主题自带的 DejaVu Sans 不含中文字形，中英混排统一用雅黑）
 *
 * 生成：NODE_PATH=$(npm root -g) node build_deck.js
 * 转 PDF：python ~/.claude/skills/pptx/scripts/wps_convert.py <生成的 .pptx>
 */

const pptxgen = require('pptxgenjs');
const path = require('path');

// ============================================================
// 主题与版式
// ============================================================

const W = 13.333;
const H = 7.5;

const C = {
  blue: '0066FF',
  blueDeep: '0044B8',
  cyan: '00FFFF',
  dark: '1E1E1E',
  dark2: '2B2F36',
  white: 'FFFFFF',
  gray: '98A2B3',
  line: 'E4E9F2',
  bgSoft: 'F5F7FB',
  text: '1C2430',
  textSub: '5B6577',
};

const F = 'Microsoft YaHei';

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.author = 'Alpha 小队';
pres.title = '深镜智聘 · 项目的详细分工及过程';

let pageNo = 0;

const FIG = (n) => path.join(__dirname, 'figures', n);
const UI = (n) => path.join(__dirname, 'figures', 'ui', n);
const TEAM = (n) => path.join(__dirname, 'figures', 'team', n);

function baseSlide(title, kicker) {
  const s = pres.addSlide();
  s.background = { color: C.white };
  s.addShape('rect', { x: 0, y: 0, w: W, h: 0.95, fill: { color: C.dark } });
  s.addShape('rect', { x: 0, y: 0, w: 0.16, h: 0.95, fill: { color: C.blue } });
  s.addText(title, {
    x: 0.52, y: 0.16, w: 10.2, h: 0.63,
    fontSize: 23, bold: true, color: C.white, fontFace: F, margin: 0, valign: 'middle',
  });
  if (kicker) {
    s.addText(kicker, {
      x: 11.0, y: 0.2, w: 1.9, h: 0.55,
      fontSize: 11, color: C.cyan, align: 'right', fontFace: F, margin: 0, valign: 'middle',
    });
  }
  pageNo += 1;
  s.addText('深镜智聘 · Alpha 小队', {
    x: 0.52, y: H - 0.46, w: 5, h: 0.3, fontSize: 9.5, color: C.gray, fontFace: F, margin: 0,
  });
  s.addText(String(pageNo).padStart(2, '0'), {
    x: W - 1.15, y: H - 0.46, w: 0.63, h: 0.3,
    fontSize: 9.5, color: C.gray, align: 'right', fontFace: F, margin: 0,
  });
  return s;
}

function bullets(s, items, x, y, w, rowH, fs) {
  rowH = rowH || 0.96;
  fs = fs || 12.5;
  items.forEach((it, i) => {
    const yy = y + i * rowH;
    s.addShape('rect', { x, y: yy + 0.12, w: 0.1, h: 0.1, fill: { color: C.blue } });
    s.addText(
      [
        { text: it[0] + '　', options: { bold: true, color: C.text } },
        { text: it[1], options: { color: C.textSub } },
      ],
      {
        x: x + 0.3, y: yy - 0.04, w: w - 0.3, h: rowH - 0.06,
        fontSize: fs, fontFace: F, margin: 0, valign: 'top', lineSpacingMultiple: 1.12,
      }
    );
  });
}

function statCard(s, x, y, w, h, num, label, sub) {
  s.addShape('roundRect', {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: C.bgSoft }, line: { color: C.line, width: 1 },
  });
  s.addText(num, {
    x: x + 0.24, y: y + 0.14, w: w - 0.48, h: 0.62,
    fontSize: 30, bold: true, color: C.blue, fontFace: F, margin: 0,
  });
  s.addText(label, {
    x: x + 0.24, y: y + 0.76, w: w - 0.48, h: 0.34,
    fontSize: 13, bold: true, color: C.text, fontFace: F, margin: 0,
  });
  if (sub) {
    s.addText(sub, {
      x: x + 0.24, y: y + 1.1, w: w - 0.48, h: h - 1.16,
      fontSize: 10, color: C.gray, fontFace: F, margin: 0, valign: 'top',
    });
  }
}

/** 界面截图 + 底部标签（contain 自适应，卡片衬底）。 */
function uiShot(s, x, y, w, h, img, label) {
  s.addShape('roundRect', {
    x, y, w, h, rectRadius: 0.04,
    fill: { color: C.bgSoft }, line: { color: C.line, width: 1 },
  });
  s.addImage({ path: img, x: x + 0.06, y: y + 0.06, sizing: { type: 'contain', w: w - 0.12, h: h - 0.12 } });
  s.addText(label, {
    x, y: y + h + 0.04, w, h: 0.28,
    fontSize: 10, color: C.textSub, align: 'center', fontFace: F, margin: 0,
  });
}

/** 横向流程条：圆角节点 + 箭头。 */
function flowBar(s, nodes, x, y, w) {
  const n = nodes.length;
  const gap = 0.42;
  const bw = (w - (n - 1) * gap) / n;
  const bh = 0.95;
  nodes.forEach((nd, i) => {
    const bx = x + i * (bw + gap);
    s.addShape('roundRect', { x: bx, y, w: bw, h: bh, rectRadius: 0.06, fill: { color: i === n - 1 ? C.blueDeep : C.blue } });
    s.addText(nd[0], {
      x: bx + 0.1, y: y + 0.1, w: bw - 0.2, h: 0.4,
      fontSize: 13.5, bold: true, color: C.white, align: 'center', fontFace: F, margin: 0,
    });
    s.addText(nd[1], {
      x: bx + 0.1, y: y + 0.5, w: bw - 0.2, h: 0.4,
      fontSize: 9, color: 'D8E4FF', align: 'center', fontFace: F, margin: 0,
    });
    if (i < n - 1) {
      s.addText('▶', {
        x: bx + bw, y: y + 0.28, w: gap, h: 0.4,
        fontSize: 11, color: C.gray, align: 'center', fontFace: F, margin: 0,
      });
    }
  });
}

/** 横向条形图（自绘）。 */
function hbarChart(s, items, x, y, w, labelW, rowH, color) {
  const max = Math.max(...items.map((it) => it[1]));
  const barMax = w - labelW - 1.0;
  items.forEach((it, i) => {
    const yy = y + i * rowH;
    s.addText(it[0], {
      x, y: yy, w: labelW - 0.15, h: 0.34,
      fontSize: 11, color: C.text, align: 'right', fontFace: F, margin: 0, valign: 'middle',
    });
    s.addShape('rect', { x: x + labelW, y: yy + 0.07, w: barMax, h: 0.2, fill: { color: C.bgSoft } });
    s.addShape('rect', {
      x: x + labelW, y: yy + 0.07, w: Math.max(barMax * (it[1] / max), 0.08), h: 0.2,
      fill: { color: color || C.blue },
    });
    s.addText(String(it[1]), {
      x: x + labelW + barMax + 0.12, y: yy, w: 0.9, h: 0.34,
      fontSize: 11, bold: true, color: C.text, fontFace: F, margin: 0, valign: 'middle',
    });
  });
}

// ============================================================
// P1 封面
// ============================================================

(function cover() {
  const s = pres.addSlide();
  s.background = { color: C.dark };

  s.addShape('rect', { x: W - 3.4, y: 0, w: 3.4, h: H, fill: { color: C.dark2 } });
  s.addShape('rect', { x: W - 3.4, y: 0, w: 0.05, h: H, fill: { color: C.blue } });
  s.addShape('rect', { x: W - 2.6, y: 1.1, w: 1.5, h: 0.1, fill: { color: C.cyan } });
  s.addShape('rect', { x: W - 2.6, y: 1.35, w: 0.95, h: 0.1, fill: { color: C.blue } });
  s.addShape('rect', { x: W - 2.6, y: 1.6, w: 0.55, h: 0.1, fill: { color: '3A4048' } });
  s.addShape('ellipse', { x: W - 2.2, y: 4.6, w: 1.15, h: 1.15, fill: { color: C.blue } });
  s.addShape('ellipse', { x: W - 1.75, y: 5.15, w: 0.7, h: 0.7, fill: { color: C.cyan } });
  s.addShape('ellipse', { x: W - 1.42, y: 5.5, w: 0.24, h: 0.24, fill: { color: C.dark } });

  s.addText('深镜智聘', {
    x: 0.85, y: 1.55, w: 8.4, h: 1.35,
    fontSize: 58, bold: true, color: C.white, fontFace: F, margin: 0, charSpacing: 2,
  });
  s.addText('基于多模态交互与动态知识图谱的计算机岗位\nAI 模拟面试与能力提升平台', {
    x: 0.9, y: 3.0, w: 8.6, h: 1.05,
    fontSize: 15.5, color: C.cyan, fontFace: F, margin: 0, lineSpacing: 27,
  });
  s.addShape('rect', { x: 0.9, y: 4.35, w: 3.1, h: 0.045, fill: { color: C.blue } });
  s.addText('项目的详细分工及过程', {
    x: 0.9, y: 4.62, w: 8.4, h: 0.55,
    fontSize: 21, color: C.white, fontFace: F, margin: 0,
  });
  s.addText('Alpha 小队｜2026 年 10 月', {
    x: 0.9, y: 6.15, w: 8.4, h: 0.42,
    fontSize: 13, color: C.gray, fontFace: F, margin: 0,
  });
})();

// ============================================================
// P2 目录（左侧色块 + 右侧条目）
// ============================================================

(function toc() {
  const s = pres.addSlide();
  s.background = { color: C.white };
  s.addShape('rect', { x: 0, y: 0, w: 4.3, h: H, fill: { color: C.dark } });
  s.addShape('rect', { x: 0, y: 0, w: 0.16, h: H, fill: { color: C.blue } });
  s.addText('目录', {
    x: 0.75, y: 2.7, w: 3.2, h: 0.95, fontSize: 40, bold: true, color: C.white, fontFace: F, margin: 0,
  });
  s.addText('CONTENTS', {
    x: 0.78, y: 3.65, w: 3.2, h: 0.4, fontSize: 13, color: C.cyan, fontFace: F, margin: 0, charSpacing: 3,
  });
  s.addShape('rect', { x: 0.78, y: 4.15, w: 1.4, h: 0.045, fill: { color: C.blue } });

  const cols = [
    { x: 5.1, no: '01', title: '团队分工', items: ['团队构成与分工原则', '五个岗位的职责与产出', '协作机制'] },
    { x: 9.3, no: '02', title: '项目实施过程', items: ['实施路线与四个阶段', '风险与应对', '阶段任务与人员分工'] },
  ];
  cols.forEach((c) => {
    s.addText(c.no, {
      x: c.x, y: 1.62, w: 1.5, h: 0.95, fontSize: 42, bold: true, color: C.line, fontFace: F, margin: 0,
    });
    s.addText(c.title, {
      x: c.x + 1.25, y: 1.78, w: 3.6, h: 0.6, fontSize: 21, bold: true, color: C.text, fontFace: F, margin: 0,
    });
    s.addShape('rect', { x: c.x + 1.25, y: 2.5, w: 0.6, h: 0.05, fill: { color: C.blue } });
    c.items.forEach((t, i) => {
      const yy = 2.95 + i * 0.72;
      s.addShape('rect', { x: c.x + 1.25, y: yy + 0.17, w: 0.09, h: 0.09, fill: { color: C.cyan } });
      s.addText(t, {
        x: c.x + 1.52, y: yy, w: 3.4, h: 0.46, fontSize: 13.5, color: C.textSub, fontFace: F, margin: 0,
      });
    });
  });
})();

// ============================================================
// P3 项目一览
// ============================================================

(function overview() {
  const s = baseSlide('项目一览', 'OVERVIEW');

  s.addText('面向计算机岗位的 AI 模拟面试与能力提升平台：多轮动态追问、五维能力评估、成长追踪闭环。', {
    x: 0.75, y: 1.22, w: 11.9, h: 0.5,
    fontSize: 14, color: C.textSub, fontFace: F, margin: 0,
  });

  const cards = [
    ['5012', '道结构化题目', '覆盖 5 个技术岗位，每题 18 个字段'],
    ['74011', '条向量检索条目', '语义召回 + 交叉编码器精排'],
    ['180', '项自动化测试', '全量运行约 10 秒，测试库隔离'],
    ['2000', '场流程仿真', '5 岗位 × 400 场，兜底 0 次'],
    ['7 / 10', '轮制双链路', '原链路 7 轮制与引擎 10 题制并存'],
    ['5', '维能力评估', '技术 · 逻辑 · 表达 · 应变 · 匹配'],
  ];

  cards.forEach((c, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    statCard(s, 0.75 + col * 4.0, 2.0 + row * 2.05, 3.75, 1.85, c[0], c[1], c[2]);
  });
})();

// ============================================================
// P4 团队构成与分工原则（链路图 + 表格）
// ============================================================

(function team() {
  const s = baseSlide('团队构成与分工原则', '团队分工 · 1.1');

  s.addText('5 人团队，采用「技术分工 + 文档共建」的协作模式，按技术链路一人负责一段。', {
    x: 0.75, y: 1.14, w: 11.9, h: 0.4,
    fontSize: 13, color: C.textSub, fontFace: F, margin: 0,
  });

  // 协作链路：前端 → 主后端 → 两类 AI 服务
  const ly = 1.68;
  s.addShape('roundRect', { x: 0.9, y: ly, w: 2.0, h: 0.72, rectRadius: 0.06, fill: { color: C.dark } });
  s.addText('前端界面\n5173 / 同端口', {
    x: 0.9, y: ly + 0.08, w: 2.0, h: 0.56, fontSize: 10.5, color: C.white, align: 'center', fontFace: F, margin: 0,
  });
  s.addText('▶', { x: 2.95, y: ly + 0.16, w: 0.5, h: 0.4, fontSize: 13, color: C.blue, align: 'center', fontFace: F, margin: 0 });
  s.addShape('roundRect', { x: 3.5, y: ly, w: 2.5, h: 0.72, rectRadius: 0.06, fill: { color: C.blue } });
  s.addText('主后端 8001\n统一接口与转发', {
    x: 3.5, y: ly + 0.08, w: 2.5, h: 0.56, fontSize: 10.5, color: C.white, align: 'center', fontFace: F, margin: 0,
  });
  s.addText('▶', { x: 6.05, y: ly + 0.16, w: 0.5, h: 0.4, fontSize: 13, color: C.blue, align: 'center', fontFace: F, margin: 0 });
  s.addShape('roundRect', { x: 6.6, y: ly, w: 2.9, h: 0.72, rectRadius: 0.06, fill: { color: C.bgSoft }, line: { color: C.blue, width: 1.25 } });
  s.addText('AI 对话与评估层 8005', {
    x: 6.6, y: ly + 0.17, w: 2.9, h: 0.4, fontSize: 10.5, color: C.text, align: 'center', fontFace: F, margin: 0,
  });
  s.addShape('roundRect', { x: 9.9, y: ly, w: 2.9, h: 0.72, rectRadius: 0.06, fill: { color: C.bgSoft }, line: { color: C.blue, width: 1.25 } });
  s.addText('知识库检索服务 8003', {
    x: 9.9, y: ly + 0.17, w: 2.9, h: 0.4, fontSize: 10.5, color: C.text, align: 'center', fontFace: F, margin: 0,
  });

  const rows = [
    [
      { text: '岗位', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '负责模块', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '核心职责', options: { bold: true, color: C.white, fill: { color: C.blue } } },
    ],
    ['后端开发 A · 小丁', '主后端与系统集成', '数据模型与接口体系、面试流程编排、AI 能力接入与降级、部署与一键启动'],
    ['AI 对话层与面试官人格 · 小陈', '对话层服务与面试官算法', '面试官人格提示词、动态追问逻辑与节奏控制、知识图谱与检索接入、语音转写与成长档案'],
    ['AI 评估与报告生成 · 小黄', '评估能力', '五维评分提示词、按题校准、语音指标分析、报告文本生成、项目文档统筹'],
    ['前端全栈开发 · 小冯', '正式前端', '14 个页面与 1 个设置组件的交互实现、语音录制与播放、报告可视化、构建产物交付'],
    ['知识库构建与测试 · 小李', '题库与检索', '5012 题题库生产与导入、74011 条向量检索服务、RAG 检索接口、全流程功能测试'],
  ];

  s.addTable(rows, {
    x: 0.75, y: 2.75, w: 11.85,
    colW: [2.2, 2.85, 6.8],
    fontSize: 11, fontFace: F, color: C.text,
    border: { type: 'solid', color: C.line, pt: 0.75 },
    fill: { color: C.white }, valign: 'middle', margin: 0.07,
    rowH: 0.53,
  });
})();

// ============================================================
// P5 后端开发 A（左文右图）
// ============================================================

(function backendA() {
  const s = baseSlide('后端开发 A：主后端与面试状态机', '团队分工 · 1.2');

  bullets(s, [
    ['数据基座', '8 张业务表；词表收敛到唯一定义处'],
    ['流程编排', '表驱动状态机；1 道开场题 + 6 轮动态追问'],
    ['断点可恢复', '出题即落库、作答再回填，任意环节可恢复'],
  ], 0.8, 1.22, 6.0, 0.8, 11);
  bullets(s, [
    ['集成与高可用', '五级数据源链；超时分档 60 / 30 / 15 秒'],
    ['双链路隔离', '线路创建时定死、整场只读；失效自动收尾'],
    ['工程化交付', '180 项测试；一键启动四个进程；双远程'],
  ], 6.95, 1.22, 5.75, 0.8, 11);

  s.addShape('roundRect', { x: 2.32, y: 3.72, w: 8.7, h: 3.2, rectRadius: 0.06, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addImage({ path: FIG('fig-6-2-1-面试流程引擎.png'), x: 2.45, y: 3.82, sizing: { type: 'contain', w: 8.44, h: 3.0 } });
})();

// ============================================================
// P6 AI 对话层与面试官人格（流程条 + 要点）
// ============================================================

(function dialogue() {
  const s = baseSlide('AI 对话层与面试官人格', '团队分工 · 1.2');

  flowBar(s, [
    ['锚点定位', '历史中最近一道题库原题'],
    ['L1 基础追问', '未追问过取此层'],
    ['L2 递进追问', '已追问一次'],
    ['L3 拓展追问', '已追问两次'],
    ['换新题', '三次以上或到收尾轮'],
  ], 0.8, 1.25, 11.85);

  bullets(s, [
    ['露怯的降级引导', '答案不足 20 字或出现 12 个露怯短语时，追问改为降级话术，把考生拉回可回答的层面'],
    ['收尾控制', '第 6、7 轮强制换新题并偏向行为素质题；连续露怯的考生跳过深度压轴题'],
    ['V5 换代三处重写', '素材字段直读（119 行正则层作废）；L1 触发改语义分流，追问触达率 66% → 100%；收尾题池改按题型选取'],
    ['对话层服务', '8005 独立运行：面试官人格提示词、追问生成、语音转写、成长档案与考后复盘'],
    ['效果验证', '骨架经两轮审查与 2700 场模拟；迭代后按 5 岗位 × 400 场回归，兜底 0 次、收尾题 100%'],
  ], 0.8, 2.6, 11.85, 0.78, 12);

  s.addShape('rect', { x: 0.8, y: 6.42, w: 11.85, h: 0.6, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addText('主要产出：interviewer_new 算法模块与说明 · 对话层服务及其集成适配 · 算法测试用例', {
    x: 1.02, y: 6.47, w: 11.4, h: 0.5,
    fontSize: 10.5, color: C.textSub, fontFace: F, margin: 0, valign: 'middle',
  });
})();

// ============================================================
// P7 AI 评估与报告生成（双模型对比 + 权重图）
// ============================================================

(function evaluator() {
  const s = baseSlide('AI 评估与报告生成', '团队分工 · 1.2');

  // 双模型三卡横排
  const cards = [
    ['客观线 · Qwen', '把回答抽成技术主张、标准答案拆成原子断言，逐条判断支持、矛盾或证据不足'],
    ['主观线 · DeepSeek', '五维评价与判档：技术 / 逻辑 / 表达 / 应变 / 匹配'],
    ['合成方式', '两条线按置信度感知权重合成最终分数，不采用固定比例加权'],
  ];
  cards.forEach((c, i) => {
    const xx = 0.8 + i * 4.02;
    s.addShape('roundRect', { x: xx, y: 1.22, w: 3.85, h: 1.3, rectRadius: 0.05, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
    s.addShape('rect', { x: xx, y: 1.22, w: 3.85, h: 0.09, fill: { color: C.blue } });
    s.addText(c[0], { x: xx + 0.2, y: 1.4, w: 3.45, h: 0.36, fontSize: 12, bold: true, color: C.text, fontFace: F, margin: 0 });
    s.addText(c[1], { x: xx + 0.2, y: 1.78, w: 3.45, h: 0.68, fontSize: 9.5, color: C.textSub, fontFace: F, margin: 0, valign: 'top' });
  });

  // 表达指标（紧凑一行）+ 按题校准（右侧）
  s.addText(
    [
      { text: '表达指标口径　', options: { bold: true, color: C.blue } },
      { text: '语速 = 去标点字数 ÷ 净说话分钟　·　长停顿 = 人声间隔 > 1500ms　·　填充词按字面量匹配　·　音量稳定性 = 3 秒窗 RMS 标准差 ÷ 均值；停顿检测基于人声活动检测，而非转写段间隔', options: { color: C.textSub } },
    ],
    { x: 0.8, y: 2.68, w: 11.85, h: 0.62, fontSize: 10, fontFace: F, margin: 0, valign: 'top', lineSpacingMultiple: 1.15 }
  );

  // 权重图横跨
  s.addShape('roundRect', { x: 1.92, y: 3.42, w: 9.5, h: 3.4, rectRadius: 0.06, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addImage({ path: FIG('fig-8-2-1-岗位权重对比.png'), x: 2.05, y: 3.52, sizing: { type: 'contain', w: 9.24, h: 3.2 } });
})();

// ============================================================
// P8 前端全栈开发（界面截图网格）
// ============================================================

(function frontend() {
  const s = baseSlide('前端全栈开发', '团队分工 · 1.2');

  s.addText('Vue 3 + Vite，14 个页面 + 1 个设置组件，桌面与移动端响应式；以下为实际交付界面的部分截图。', {
    x: 0.78, y: 1.12, w: 11.9, h: 0.4,
    fontSize: 12, color: C.textSub, fontFace: F, margin: 0,
  });

  const shots = [
    [UI('ui-岗位大厅.png'), '岗位大厅：五个岗位卡片'],
    [UI('ui-面试对话室.png'), '面试对话室：文本 + 语音作答'],
    [UI('ui-报告页.png'), '报告页：雷达图与成长曲线'],
    [UI('ui-题库中心.png'), '题库中心：5012 题可检索'],
    [UI('ui-个人中心.png'), '个人中心：资料与历史'],
  ];
  const w1 = 3.85, h1 = 1.98;
  shots.forEach((sh, i) => {
    if (i < 3) {
      uiShot(s, 0.72 + i * 4.02, 1.68, w1, h1, sh[0], sh[1]);
    } else {
      uiShot(s, 2.73 + (i - 3) * 4.02, 4.22, w1, h1, sh[0], sh[1]);
    }
  });

  s.addText('语音两级设计：本地 Vosk 实时预览 + 服务端转写为准；转写失败保留本地文本并提示，可手动修改后继续。', {
    x: 0.78, y: 6.68, w: 11.9, h: 0.36,
    fontSize: 10.5, color: C.textSub, fontFace: F, margin: 0,
  });
})();

// ============================================================
// P9 知识库构建与测试（数据卡 + 条形图）
// ============================================================

(function knowledge() {
  const s = baseSlide('知识库构建与测试', '团队分工 · 1.2');

  const stats = [
    ['5012', '道结构化题目', '5 个岗位 · 每题 18 字段'],
    ['74011', '条向量检索条目', '8003 服务两段式检索'],
    ['2824', '项冒烟测试全过', '另有 169 项单元与接口测试'],
  ];
  stats.forEach((c, i) => {
    statCard(s, 0.78 + i * 4.02, 1.2, 3.8, 1.6, c[0], c[1], c[2]);
  });

  s.addText('岗位题量分布', {
    x: 0.78, y: 3.05, w: 7, h: 0.36, fontSize: 12.5, bold: true, color: C.text, fontFace: F, margin: 0,
  });
  hbarChart(s, [
    ['Java 后端开发', 2146],
    ['Web 前端开发', 734],
    ['系统设计工程师', 810],
    ['测试开发', 667],
    ['算法工程师', 655],
  ], 0.78, 3.5, 7.3, 1.75, 0.5);

  s.addShape('roundRect', { x: 8.5, y: 3.05, w: 4.13, h: 3.42, rectRadius: 0.06, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addText('质量治理与测试', {
    x: 8.72, y: 3.2, w: 3.7, h: 0.36, fontSize: 12, bold: true, color: C.text, fontFace: F, margin: 0,
  });
  bullets(s, [
    ['题库来源', '公开资料库 + 大厂真题语料 + 团队原创'],
    ['治理重写', 'L1 追问 3230 · L2 2682 · L3 2915 · 降级策略 5012 条'],
    ['测试覆盖', '数据 / 算法 / 接口 / 页面 / 异常降级五层'],
    ['典型问题', '图谱不一致 444 / 939 题；检索超时 5 秒误判改 60 秒'],
  ], 8.72, 3.62, 3.75, 0.7, 9.5);
})();

// ============================================================
// P10 协作机制（要点 + 端口表）
// ============================================================

(function collab() {
  const s = baseSlide('协作机制', '团队分工 · 1.3');

  bullets(s, [
    ['接口契约先行', '接口文档是唯一权威；前端不直接访问 AI 服务，请求经主后端统一转发'],
    ['安全边界', 'AI 服务对外只暴露结构化字段与评分结果，密钥与内部提示词不出服务边界'],
    ['例会与沟通', '线下会议与腾讯会议为正式讨论场合，即时通讯随时对接；关键节点组织全体会议'],
    ['版本管理与交付', 'Git 版本管理；GitHub 与 Gitee 双远程；密钥与运行数据不入库；一键启动'],
  ], 0.8, 1.3, 11.85, 1.02, 12);

  s.addText('端口分配', {
    x: 0.8, y: 5.42, w: 4, h: 0.35, fontSize: 13, bold: true, color: C.text, fontFace: F, margin: 0,
  });

  const rows = [
    [
      { text: '8001 主后端', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '8002 评估服务', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '8003 知识库检索', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '8005 对话与评估层', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '5173 前端开发', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '5273 演示前端', options: { bold: true, color: C.white, fill: { color: C.blue } } },
    ],
    ['后端开发 A', 'AI 评估与报告生成', '知识库构建与测试', 'AI 对话层与面试官人格', '前端全栈开发', '后端开发 A'],
  ];

  s.addTable(rows, {
    x: 0.8, y: 5.8, w: 11.85,
    colW: [2.2, 2.2, 2.2, 2.2, 1.75, 1.3],
    fontSize: 10.5, fontFace: F, color: C.textSub,
    border: { type: 'solid', color: C.line, pt: 0.75 },
    valign: 'middle', margin: 0.06, rowH: 0.42, align: 'center',
  });
})();

// ============================================================
// P11 实施路线与阶段划分（甘特图全幅）
// ============================================================

(function roadmap() {
  const s = baseSlide('实施路线与阶段划分', '项目实施过程 · 2.1');

  s.addText('四个阶段推进，后两阶段并行：集成增强期间测试与文档同步起步，直到交付前收口。', {
    x: 0.75, y: 1.12, w: 11.9, h: 0.38,
    fontSize: 12, color: C.textSub, fontFace: F, margin: 0,
  });

  s.addImage({
    path: FIG('fig-2-1-项目实施甘特图.png'),
    x: 2.0, y: 1.55, w: 9.34, h: 9.34 * (578 / 1000),
  });
})();

// ============================================================
// P12 阶段一（左文右图：求职失败原因）
// ============================================================

(function stage1() {
  const s = baseSlide('阶段一：需求分析与方案设计', '项目实施过程 · 2.2');

  // 左图（含依据说明）
  s.addShape('roundRect', { x: 0.8, y: 1.18, w: 6.6, h: 5.55, rectRadius: 0.06, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addImage({ path: FIG('fig-1-2-求职失败主要原因.png'), x: 0.95, y: 1.7, sizing: { type: 'contain', w: 6.3, h: 4.2 } });
  s.addText('需求分析依据：求职失败主因调查', {
    x: 0.95, y: 6.1, w: 6.3, h: 0.4, fontSize: 10, color: C.gray, align: 'center', fontFace: F, margin: 0,
  });

  // 右文：目标 + 要点
  s.addShape('rect', { x: 7.65, y: 1.18, w: 4.9, h: 0.92, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addText(
    [
      { text: '核心目标　', options: { bold: true, color: C.blue } },
      { text: '明确系统边界与技术路线，形成可执行的分工与开发计划。', options: { color: C.text } },
    ],
    { x: 7.83, y: 1.24, w: 4.55, h: 0.8, fontSize: 10.5, fontFace: F, margin: 0, valign: 'middle', lineSpacingMultiple: 1.1 }
  );

  bullets(s, [
    ['需求梳理', '分析痛点，确定产品形态'],
    ['技术选型', 'FastAPI 异步 + Vue 3；SQLite 零配置启动'],
    ['评估体系', '五维模型与各岗位权重表'],
    ['协作约定', '目录归属、端口分配、接口先行'],
  ], 7.65, 2.3, 4.9, 0.9, 10.5);

  s.addShape('rect', { x: 7.65, y: 5.95, w: 4.9, h: 0.78, fill: { color: C.white }, line: { color: C.line, width: 1 } });
  s.addText('交付物：需求文档 · 功能清单 · 评估维度定义 · 接口初稿 · 协作指南', {
    x: 7.83, y: 6.0, w: 4.55, h: 0.68, fontSize: 9.5, color: C.textSub, fontFace: F, margin: 0, valign: 'middle',
  });
})();

// ============================================================
// P13 阶段二（模块卡片 + 链路图）
// ============================================================

(function stage2() {
  const s = baseSlide('阶段二：核心功能开发', '项目实施过程 · 2.3');

  s.addShape('rect', { x: 0.8, y: 1.2, w: 11.85, h: 0.6, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addText(
    [
      { text: '核心目标　', options: { bold: true, color: C.blue } },
      { text: '跑通「创建面试 → 出题 → 作答 → 动态追问 → 结束 → 生成报告」完整闭环。', options: { color: C.text } },
    ],
    { x: 1.0, y: 1.26, w: 11.4, h: 0.48, fontSize: 11.5, fontFace: F, margin: 0, valign: 'middle' }
  );

  const mods = [
    ['后端基座', '数据模型、鉴权体系、面试状态机、统一响应与错误码；一键启动脚本'],
    ['评估能力', '五维评分与报告文本生成上线'],
    ['题库与算法', '题库入库；面试官算法原生接入数据源链，形成五级结构'],
    ['演示前端', '正式前端完成前先行交付，作为演示与联调入口'],
  ];
  mods.forEach((m, i) => {
    const xx = 0.8 + i * 3.02;
    s.addShape('roundRect', { x: xx, y: 1.98, w: 2.85, h: 1.75, rectRadius: 0.05, fill: { color: C.white }, line: { color: C.line, width: 1 } });
    s.addShape('rect', { x: xx, y: 1.98, w: 2.85, h: 0.1, fill: { color: C.blue } });
    s.addText(m[0], { x: xx + 0.18, y: 2.18, w: 2.5, h: 0.36, fontSize: 12, bold: true, color: C.text, fontFace: F, margin: 0 });
    s.addText(m[1], { x: xx + 0.18, y: 2.58, w: 2.5, h: 1.05, fontSize: 9.5, color: C.textSub, fontFace: F, margin: 0, valign: 'top' });
  });

  // V5 换代横跨深色卡：三段式
  s.addShape('roundRect', { x: 0.8, y: 3.95, w: 11.85, h: 2.62, rectRadius: 0.06, fill: { color: C.dark } });
  s.addShape('rect', { x: 0.8, y: 3.95, w: 0.14, h: 2.62, fill: { color: C.blue } });
  s.addText('V5 换代　一次迭代，三层重做', {
    x: 1.12, y: 4.1, w: 10.5, h: 0.45, fontSize: 14, bold: true, color: C.cyan, fontFace: F, margin: 0,
  });
  const v5 = [
    ['题库', '从数百题扩充至 5012 题，补齐得分点与三级追问'],
    ['算法', '面试官算法按新结构重写，追问触达率 66% → 100%'],
    ['检索与评估', 'RAG 服务接入数据源链；评估按题注入校准锚点'],
  ];
  v5.forEach((t, i) => {
    const xx = 1.12 + i * 3.85;
    s.addShape('rect', { x: xx, y: 4.78, w: 0.09, h: 0.09, fill: { color: C.cyan } });
    s.addText(t[0], { x: xx + 0.2, y: 4.66, w: 3.4, h: 0.34, fontSize: 11.5, bold: true, color: C.white, fontFace: F, margin: 0 });
    s.addText(t[1], { x: xx + 0.2, y: 5.04, w: 3.45, h: 1.3, fontSize: 9.5, color: 'C9D4E8', fontFace: F, margin: 0, valign: 'top' });
  });

  s.addText('交付物：主后端服务 · 评估能力 · 面试官算法 · V5 题库与检索服务 · 演示前端 · 接口与对接文档', {
    x: 0.8, y: 6.72, w: 11.85, h: 0.34, fontSize: 10.5, color: C.textSub, fontFace: F, margin: 0,
  });
})();

// ============================================================
// P14 阶段三（能力网格）
// ============================================================

(function stage3() {
  const s = baseSlide('阶段三：系统集成与能力增强', '项目实施过程 · 2.4');

  s.addShape('rect', { x: 0.8, y: 1.2, w: 11.85, h: 0.6, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addText(
    [
      { text: '核心目标　', options: { bold: true, color: C.blue } },
      { text: '在闭环之上扩展功能面与 AI 能力，形成练习、评估、提升的完整闭环。', options: { color: C.text } },
    ],
    { x: 1.0, y: 1.26, w: 11.4, h: 0.48, fontSize: 11.5, fontFace: F, margin: 0, valign: 'middle' }
  );

  const caps = [
    ['个人中心', '资料编辑、头像上传、按岗位筛选的历史与成长曲线'],
    ['报告分享', '限时免登录分享链接，重复生成复用未过期链接'],
    ['学习资源', '学习计划推荐上线，按评估结果给出提升路径'],
    ['简历导入', '上传解析后可回填至面试上下文'],
    ['对话层迭代', '三个版本：语音转写、成长档案、考后复盘、朗读与体态'],
    ['语音读数回传', '语速、停顿等读数随作答回传，参与报告生成'],
  ];
  caps.forEach((m, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const xx = 0.8 + col * 4.02;
    const yy = 2.05 + row * 1.72;
    s.addShape('roundRect', { x: xx, y: yy, w: 3.85, h: 1.55, rectRadius: 0.05, fill: { color: C.white }, line: { color: C.line, width: 1 } });
    s.addShape('rect', { x: xx, y: yy, w: 0.1, h: 1.55, fill: { color: C.blue } });
    s.addText(m[0], { x: xx + 0.28, y: yy + 0.18, w: 3.4, h: 0.38, fontSize: 13, bold: true, color: C.text, fontFace: F, margin: 0 });
    s.addText(m[1], { x: xx + 0.28, y: yy + 0.6, w: 3.4, h: 0.85, fontSize: 10, color: C.textSub, fontFace: F, margin: 0, valign: 'top' });
  });

  s.addText('前端集中开发：后端按需求文档分批交付接口，前端完成后交付 25 条接口对照表，双方逐条核对修正。', {
    x: 0.8, y: 5.6, w: 11.85, h: 0.36, fontSize: 11, color: C.textSub, fontFace: F, margin: 0,
  });
  s.addText('交付物：个人中心与分享接口 · 简历与学习资源接口 · 对话层服务集成 · 语音能力 · 前端全部页面与联调记录', {
    x: 0.8, y: 6.68, w: 11.85, h: 0.34, fontSize: 10.5, color: C.textSub, fontFace: F, margin: 0,
  });
})();

// ============================================================
// P15 阶段四（大数字 + 文档清单）
// ============================================================

(function stage4() {
  const s = baseSlide('阶段四：测试优化与成果交付', '项目实施过程 · 2.5');

  s.addShape('rect', { x: 0.8, y: 1.2, w: 11.85, h: 0.6, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addText(
    [
      { text: '核心目标　', options: { bold: true, color: C.blue } },
      { text: '验证质量、优化性能，完成全套成果材料的整理与提交。', options: { color: C.text } },
    ],
    { x: 1.0, y: 1.26, w: 11.4, h: 0.48, fontSize: 11.5, fontFace: F, margin: 0, valign: 'middle' }
  );

  const nums = [
    ['180', '项自动化测试', '覆盖全部核心模块'],
    ['2824', '项冒烟测试', '全部通过、失败 0 项'],
    ['2000', '场流程仿真', '5 岗位 × 400 场'],
    ['10 秒', '全量测试耗时', '测试库与开发库隔离'],
  ];
  nums.forEach((c, i) => {
    statCard(s, 0.8 + i * 3.02, 2.02, 2.85, 1.75, c[0], c[1], c[2]);
  });

  s.addText('验证与优化动作', {
    x: 0.8, y: 4.02, w: 6, h: 0.36, fontSize: 12.5, bold: true, color: C.text, fontFace: F, margin: 0,
  });
  bullets(s, [
    ['效果回归', '每次算法与数据迭代后重跑仿真，以「兜底 0 次、收尾题 100%」为基线'],
    ['并发优化', '写前日志模式与忙等超时配置，多场面试并发提交不锁库'],
    ['前端部署', '构建产物拷入主服务静态目录，同端口挂载'],
  ], 0.8, 4.45, 7.6, 0.68, 10.5);

  s.addShape('roundRect', { x: 8.55, y: 4.02, w: 4.1, h: 2.42, rectRadius: 0.06, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addText('文档与材料', {
    x: 8.75, y: 4.15, w: 3.7, h: 0.36, fontSize: 12, bold: true, color: C.text, fontFace: F, margin: 0,
  });
  ['开发手册与新增代码清单', '竞赛三册材料', '详细方案章节稿与配图', '前端联调指南', '本材料'].forEach((t, i) => {
    const yy = 4.58 + i * 0.36;
    s.addShape('rect', { x: 8.75, y: yy + 0.09, w: 0.09, h: 0.09, fill: { color: C.blue } });
    s.addText(t, { x: 9.0, y: yy - 0.02, w: 3.5, h: 0.32, fontSize: 10, color: C.textSub, fontFace: F, margin: 0 });
  });
})();

// ============================================================
// P16 风险与应对
// ============================================================

(function risks() {
  const s = baseSlide('风险与应对', '项目实施过程 · 2.6');

  const rows = [
    [
      { text: '风险', options: { bold: true, color: C.white, fill: { color: C.blue } } },
      { text: '应对措施', options: { bold: true, color: C.white, fill: { color: C.blue } } },
    ],
    ['外部服务（大模型、知识库）不可用或超时', '五级数据源降级链逐级兜底；内置兜底不依赖任何外部服务；超时预算按实测耗时分档'],
    ['题库换代导致算法与评估失效', '换代后重跑全岗位流程仿真；受控词表集中定义，非法值直接报错而非静默返回空集'],
    ['大模型调用成本随使用量增长', '优化提示词长度；高频场景建立缓存；精度允许时以小模型处理简单场景'],
    ['语音识别在真人场景下准确率不确定', '提供转写文本手动校对；持续优化语音活动检测参数与热词表'],
    ['数据隐私与合规', '录音即用即删，不进数据库、不进日志；用户可随时删除自己的面试记录'],
    ['运行环境差异导致服务起不来', '启动脚本纯 ASCII 引导规避终端编码差异；向量库目录固定纯 ASCII 名'],
  ];

  s.addTable(rows, {
    x: 0.8, y: 1.35, w: 11.85,
    colW: [4.1, 7.75],
    fontSize: 11.5, fontFace: F, color: C.textSub,
    border: { type: 'solid', color: C.line, pt: 0.75 },
    valign: 'middle', margin: 0.1, rowH: 0.78,
  });
})();

// ============================================================
// P17-P18 阶段任务与人员分工表
// ============================================================

const HEAD = [
  { text: '阶段', options: { bold: true, color: C.white, fill: { color: C.blue } } },
  { text: '关键任务', options: { bold: true, color: C.white, fill: { color: C.blue } } },
  { text: '任务描述', options: { bold: true, color: C.white, fill: { color: C.blue } } },
  { text: '时间', options: { bold: true, color: C.white, fill: { color: C.blue } } },
  { text: '负责岗位', options: { bold: true, color: C.white, fill: { color: C.blue } } },
  { text: '交付物', options: { bold: true, color: C.white, fill: { color: C.blue } } },
];

const PLAN_12 = [
  HEAD,
  ['一、需求分析与方案设计', '需求梳理', '分析求职痛点，确定产品形态与功能范围', '8 月中旬', '全队', '产品需求文档、功能清单'],
  ['', '技术选型', '确定框架、数据库、服务拆分与部署方式', '8 月中旬', '小丁主导', '技术方案'],
  ['', '评估体系设计', '五维评分模型与各岗位权重', '8 月中旬', '小黄，全队审定', '评估维度定义'],
  ['', '分工与协作约定', '目录归属、端口分配、接口契约规范', '8 月下旬', '全队', '协作指南、接口初稿'],
  ['二、核心功能开发', '后端基座', '数据模型、鉴权、状态机、异常体系、一键启动', '8 月下旬', '小丁', '主后端服务'],
  ['', '评估能力', '五维评分与报告文本生成', '9 月上旬', '小黄', '评估服务'],
  ['', '题库与面试官算法', '题库入库与算法原生接入', '9 月上旬', '小李、小陈', '题库、算法模块'],
  ['', '演示前端', '正式前端交付前的演示与联调入口', '9 月上旬', '小丁', '演示前端（5273）'],
  ['', 'V5 换代', '题库扩至 5012 题，算法、检索、评估同步重做', '9 月 14 日', '全队', 'V5 题库、检索服务'],
];

const PLAN_34 = [
  HEAD,
  ['三、系统集成与能力增强', '个人中心与报告分享', '资料编辑、头像、按岗位筛选、限时分享链接', '9 月中旬', '小丁', '相关接口'],
  ['', '学习资源与简历', '学习计划推荐、简历上传解析与回填', '9 月下旬', '小丁', '相关接口'],
  ['', '对话层服务迭代', '三版迭代、语音转写、成长档案、考后复盘', '9 月下旬', '小陈、小丁', '对话层服务集成'],
  ['', '前端集中开发与联调', '14 个页面实现，接口对照逐条核对', '9 月下旬至 10 月上旬', '小冯', '构建产物'],
  ['四、测试优化与成果交付', '测试与仿真', '180 项自动化用例、全岗位流程仿真', '9 月上旬起持续', '小丁', '测试套件、仿真数据'],
  ['', '性能与并发优化', '并发写入配置、超时预算分档', '9 月下旬', '小丁', '优化配置'],
  ['', '文档与材料', '开发手册、代码清单、三册材料、章节稿、本文', '9 月中旬至 10 月上旬', '全队（小黄统筹）', '全套提交材料'],
];

[
  { rows: PLAN_12, title: '阶段任务与人员分工表（一）', sub: '阶段一 · 阶段二' },
  { rows: PLAN_34, title: '阶段任务与人员分工表（二）', sub: '阶段三 · 阶段四' },
].forEach((page) => {
  const s = baseSlide(page.title, '项目实施过程 · 2.7');

  s.addTable(page.rows, {
    x: 0.55, y: 1.3, w: 12.23,
    colW: [2.05, 1.75, 4.05, 1.55, 1.75, 1.08],
    fontSize: 9.5, fontFace: F, color: C.textSub,
    border: { type: 'solid', color: C.line, pt: 0.75 },
    valign: 'middle', margin: 0.05, rowH: 0.55,
  });

  s.addText('注：8 月日期依据提交记录与文档时间推断；' + page.sub, {
    x: 0.6, y: 6.75, w: 11.9, h: 0.34,
    fontSize: 9.5, color: C.gray, fontFace: F, margin: 0,
  });
});

// ============================================================
// P19 团队协作纪实
// ============================================================

(function teamwork() {
  const s = baseSlide('团队协作纪实', '协作痕迹');

  s.addText('线下集中开发与线上会议并行推进，跨成员的接口与数据对接全部以文档留痕。', {
    x: 0.8, y: 1.12, w: 11.9, h: 0.38,
    fontSize: 12, color: C.textSub, fontFace: F, margin: 0,
  });

  // 左：会议现场照片
  s.addShape('roundRect', { x: 0.8, y: 1.62, w: 6.6, h: 5.15, rectRadius: 0.05, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addImage({ path: TEAM('team-会议现场.png'), x: 0.92, y: 1.72, sizing: { type: 'contain', w: 6.36, h: 4.62 } });
  s.addText('线下集中开发（会议室现场）', {
    x: 0.92, y: 6.4, w: 6.36, h: 0.3, fontSize: 10, color: C.gray, align: 'center', fontFace: F, margin: 0,
  });

  // 右上：线上会议记录
  s.addShape('roundRect', { x: 7.65, y: 1.62, w: 4.85, h: 2.5, rectRadius: 0.05, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addImage({ path: TEAM('team-腾讯会议.png'), x: 7.77, y: 1.72, sizing: { type: 'contain', w: 4.61, h: 2.05 } });
  s.addText('线上会议对接（腾讯会议）', {
    x: 7.77, y: 3.8, w: 4.61, h: 0.28, fontSize: 10, color: C.gray, align: 'center', fontFace: F, margin: 0,
  });

  // 右下：对接文档
  s.addShape('roundRect', { x: 7.65, y: 4.27, w: 4.85, h: 2.5, rectRadius: 0.05, fill: { color: C.bgSoft }, line: { color: C.line, width: 1 } });
  s.addImage({ path: TEAM('team-对接文档核对.png'), x: 7.77, y: 4.37, sizing: { type: 'contain', w: 4.61, h: 2.05 } });
  s.addText('跨成员对接文档（接口核对）', {
    x: 7.77, y: 6.45, w: 4.61, h: 0.28, fontSize: 10, color: C.gray, align: 'center', fontFace: F, margin: 0,
  });
})();

// ============================================================
// P20 结语
// ============================================================

(function closing() {
  const s = pres.addSlide();
  s.background = { color: C.dark };

  s.addShape('rect', { x: 0, y: H / 2 - 0.02, w: W, h: 0.04, fill: { color: C.dark2 } });
  s.addShape('rect', { x: 0.9, y: 2.15, w: 0.85, h: 0.09, fill: { color: C.blue } });
  s.addShape('rect', { x: 1.9, y: 2.15, w: 0.5, h: 0.09, fill: { color: C.cyan } });

  s.addText('五个岗位，一条链路', {
    x: 0.9, y: 2.5, w: 11.5, h: 0.95,
    fontSize: 40, bold: true, color: C.white, fontFace: F, margin: 0,
  });
  s.addText('从题库生产到多模态面试，从五维评分到成长追踪，每一段都有明确的所有者与可核查的产出。', {
    x: 0.95, y: 3.62, w: 11.4, h: 0.55,
    fontSize: 14.5, color: C.gray, fontFace: F, margin: 0,
  });
  s.addText('深镜智聘｜Alpha 小队', {
    x: 0.95, y: 5.3, w: 11.4, h: 0.5,
    fontSize: 15, color: C.cyan, fontFace: F, margin: 0,
  });
})();

// ============================================================
// 输出
// ============================================================

const out = path.join(__dirname, '05-项目的详细分工及过程-演示稿.pptx');
pres.writeFile({ fileName: out }).then(() => {
  console.log('已生成:', out);
});
