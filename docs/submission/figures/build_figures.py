# -*- coding: utf-8 -*-
"""生成《项目详细方案》《项目简介 PPT》与《项目的详细分工及过程》的插图，SVG 与 PNG 各出一份。

图形由字符串拼装，PNG 交给本机 Chrome 或 Edge 的无头模式渲染，不引入第三方依赖。
改脚本顶部的 FIGURES 即可重出；新增一张图就再加一个配置字典，`type` 决定用哪个渲染器。

支持六种 type：
    hbar     横向条形图（占比、数量对比）
    flow     状态流转 + 横向流程条
    stacked  百分比堆叠条形图（多项权重对比）
    columns  并列卡片栏（分类要点）
    branch   开关分叉 + 汇聚
    gantt    项目实施甘特图（阶段色带 + 各模块工作区间）

用法：
    python build_figures.py            # 全部重出
    python build_figures.py fig-8-2    # 只重出名字里含该串的图
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent

# ============================================================
# 数据与文案
# ============================================================

FIGURES = [
    {   # 《项目详细方案》图 1-2，同时用于《项目简介 PPT》
        "file": "fig-1-2-求职失败主要原因",
        "type": "hbar",
        "title": "大学生求职失败的主要原因",
        "subtitle": "调查显示，三项均与面试环节直接相关　·　多选题，占比之和大于 100%",
        "items": [
            ("简历不过关", 50.84),
            ("面试时太紧张", 49.95),
            ("表达沟通欠缺", 49.46),
        ],
        "headroom": 1.08,      # 满量程相对最大值的上浮系数，柱尾不顶格
        "source": "数据来源：中国青年报社联合粉笔调查（2025 年 1 月，北京 10 所高校 1011 名受访者）",
    },
    {   # 详细方案 6.2 面试流程引擎
        "file": "fig-6-2-1-面试流程引擎",
        "type": "flow",
        "state_title": "面试状态机（表驱动，非法转换返回 409）",
        "states": [
            {"key": "idle", "cn": "待开始", "tone": "muted"},
            {"key": "in_progress", "cn": "进行中", "tone": "primary"},
            {"key": "finished", "cn": "已结束", "tone": "soft"},
        ],
        "edges": ["开始面试", "达到轮数上限\n或主动结束"],
        "state_note": "finished 为终态，不可再转",
        "step_title": "七轮对话闭环（1 道开场题 + 最多 6 轮追问）",
        "steps": ["开始面试", "第 1 轮\n开场题", "第 2~7 轮\n动态追问", "自动生成报告"],
    },
    {   # 详细方案 8.2 岗位差异化评分
        "file": "fig-8-2-1-岗位权重对比",
        "type": "stacked",
        "dims": [
            ("技术水平", "#3a54d6"),
            ("逻辑思维", "#5b78f0"),
            ("沟通表达", "#8ba0f5"),
            ("应变能力", "#b8c5fa"),
            ("岗位匹配度", "#dde3fd"),
        ],
        "rows": [
            ("后端开发工程师", [35, 25, 10, 10, 20]),
            ("前端开发工程师", [30, 20, 15, 15, 20]),
            ("测试开发工程师", [25, 25, 20, 15, 15]),
            ("算法工程师", [35, 30, 10, 10, 15]),
            ("系统设计工程师", [30, 30, 15, 10, 15]),
        ],
        "note": "每个岗位的五维权重之和均为 100，由模块加载期断言与测试用例双重校验",
    },
    {   # 详细方案 6.2.4 两条链路的并存与隔离
        "file": "fig-6-2-2-两条链路并存与隔离",
        "type": "branch",
        "switch": {
            "title": "DIALOGUE_ENGINE　部署级开关",
            "sub": "在 backend/.env 配置，改一处影响所有新开场的面试；已开场的场次不受影响",
        },
        "branches": [
            {
                "label": "留空（默认）",
                "title": "本项目自有链路",
                "sub": "7 轮制",
                "items": [
                    "1 道开场题 + 6 轮追问",
                    "出题：题库策略与五级降级链",
                    "评估：独立评估服务（8002）",
                ],
            },
            {
                "label": "= a11",
                "title": "AI 对话层链路",
                "sub": "10 题制",
                "items": [
                    "3 / 5 / 2 三阶段共 10 题",
                    "出题、追问、五维评分都在对话层内完成",
                    "依赖未就绪返回 503，不回落自有链路",
                ],
            },
        ],
        "footer": {
            "title": "两条链路并存，但不混用",
            "sub": "链路在开场时定死并写入面试记录，整场只读，中途不切换",
        },
    },
    {   # 详细方案 9.4 数据安全与隐私保护
        "file": "fig-9-4-1-数据安全防护点",
        "type": "columns",
        "columns": [
            {
                "title": "入口",
                "items": [
                    "鉴权：JWT（HS256）",
                    "口令：bcrypt 加盐哈希",
                    "上传：白名单 + 文件头",
                    "分享：128 位随机码",
                ],
            },
            {
                "title": "存储",
                "items": [
                    "简历存私有目录",
                    "不进任何静态挂载",
                    "只存文件名不存路径",
                    "目录已进忽略清单",
                ],
            },
            {
                "title": "出口",
                "items": [
                    "越权：资源 + 用户双条件",
                    "非本人返回「不存在」",
                    "分享：过期与不存在同提示",
                    "头像地址只收站内路径",
                ],
            },
        ],
    },
    {   # 《项目的详细分工及过程》图 2-1
        "file": "fig-2-1-项目实施甘特图",
        "type": "gantt",
        "title": "项目实施路线与各模块工作区间",
        "subtitle": "时间依据仓库提交记录与交付物时间绘制　·　阶段三与阶段四并行推进",
        "date_start": "2026-08-25",
        "date_end": "2026-10-08",
        "ticks": ["2026-08-25", "2026-09-01", "2026-09-08", "2026-09-15",
                  "2026-09-22", "2026-09-29", "2026-10-06"],
        "phases": [
            {"name": "阶段一 需求分析与方案设计", "start": None, "end": "2026-08-25",
             "row": 0, "tone": 0, "open_left": True},
            {"name": "阶段二 核心功能开发", "start": "2026-08-25", "end": "2026-09-14",
             "row": 0, "tone": 1},
            {"name": "阶段三 系统集成与能力增强", "start": "2026-09-14", "end": "2026-09-27",
             "row": 0, "tone": 2},
            {"name": "阶段四 测试优化与成果交付", "start": "2026-09-15", "end": "2026-10-08",
             "row": 1, "tone": 3},
        ],
        "rows": [
            {"name": "后端主服务与接口", "start": "2026-08-25", "end": "2026-10-04"},
            {"name": "题库与知识库", "start": "2026-09-02", "end": "2026-09-14"},
            {"name": "出题算法", "start": "2026-09-05", "end": "2026-09-14"},
            {"name": "评估服务", "start": "2026-09-02", "end": "2026-09-14"},
            {"name": "前端开发", "start": "2026-09-23", "end": "2026-10-07"},
            {"name": "对话层引擎集成", "start": "2026-09-23", "end": "2026-10-04"},
            {"name": "测试与流程仿真", "start": "2026-09-06", "end": "2026-10-04"},
            {"name": "文档与提交材料", "start": "2026-09-15", "end": "2026-10-08"},
        ],
        "source": "时间依据：2026-08-25 首次提交至 2026-10-08 的提交记录、交接文档日期与交付产物时间",
    },
]

# ============================================================
# 版式与配色（色值与演示前端 frontend_test/css/style.css 同源）
# ============================================================

FONT = "'Microsoft YaHei','PingFang SC','Hiragino Sans GB',sans-serif"

C_TEXT = "#1f2430"     # 正文
C_SUB = "#7a8296"      # 次要文字
C_LINE = "#e4e8f2"     # 分隔线
C_TRACK = "#f2f4fa"    # 柱底轨道 / 浅底
C_SOFT = "#eef1ff"     # 主色浅底
C_ACCENT = "#4f6ef7"   # 主题蓝
C_DEEP = "#3a54d6"     # 主题深蓝
WHITE = "#ffffff"

W = 1000               # 画布宽（逻辑像素）
PAD_L = 44             # 左边距

PNG_SCALE = 3          # PNG 相对逻辑尺寸的倍数，3 倍约合 300 DPI


# ============================================================
# 基础工具
# ============================================================

def esc(s: str) -> str:
    """XML 转义。"""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def text(x, y, s, *, size, fill, weight=400, anchor="start") -> str:
    return (
        f'<text x="{x:g}" y="{y:g}" font-size="{size:g}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}" font-family="{FONT}">{esc(s)}</text>'
    )


def lines(x, y, s, *, size, fill, weight=400, anchor="start", lh=None) -> str:
    """多行文本，s 内用 \\n 断行；y 为首行基线。"""
    lh = lh or size * 1.4
    return "\n".join(
        text(x, y + i * lh, part, size=size, fill=fill, weight=weight, anchor=anchor)
        for i, part in enumerate(s.split("\n"))
    )


def arrow(x1, x2, y, *, color=C_ACCENT, width=2.4, head=9) -> str:
    """水平箭头，从 x1 指向 x2。"""
    return (
        f'<line x1="{x1:g}" y1="{y:g}" x2="{x2 - head:g}" y2="{y:g}" '
        f'stroke="{color}" stroke-width="{width:g}" stroke-linecap="round"/>\n'
        f'<path d="M {x2 - head:g} {y - head * 0.62:g} L {x2:g} {y:g} '
        f'L {x2 - head:g} {y + head * 0.62:g} Z" fill="{color}"/>'
    )


def v_arrow(x, y1, y2, *, color=C_ACCENT, width=2.4, head=9) -> str:
    """竖直箭头，从 y1 指向 y2。"""
    return (
        f'<line x1="{x:g}" y1="{y1:g}" x2="{x:g}" y2="{y2 - head:g}" '
        f'stroke="{color}" stroke-width="{width:g}" stroke-linecap="round"/>\n'
        f'<path d="M {x - head * 0.62:g} {y2 - head:g} L {x:g} {y2:g} '
        f'L {x + head * 0.62:g} {y2 - head:g} Z" fill="{color}"/>'
    )


def rail(x1, x2, y, *, color=C_ACCENT, width=2.4) -> str:
    """直角折线：先竖后横（用于从一点分出两支）。"""
    return (
        f'<path d="M {x1:g} {y[0]:g} V {y[1]:g} H {x2:g}" fill="none" '
        f'stroke="{color}" stroke-width="{width:g}" stroke-linejoin="round"/>'
    )


def wrap(parts: list[str], w: int, h: int) -> str:
    """拼成完整 SVG 文档。"""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">\n'
        + "\n".join(parts)
        + "\n</svg>\n"
    )


# ============================================================
# 渲染器：横向条形图
# ============================================================

HBAR_LABEL_RIGHT = 170     # 项名右对齐位置
HBAR_X = 190               # 柱区左端
HBAR_FULL = 750            # 满量程宽度，最大项占满
HBAR_H = 58                # 柱高
HBAR_GAP = 86              # 行距
HBAR_TOP = 140             # 首行柱顶


def render_hbar(fig: dict) -> tuple[str, int, int]:
    items = fig["items"]
    vmax = max(v for _, v in items) * fig.get("headroom", 1.0)

    bar_bottom = HBAR_TOP + (len(items) - 1) * HBAR_GAP + HBAR_H
    line_y = bar_bottom + 46
    foot_y = line_y + 30
    h = foot_y + 22

    parts = [
        f"<title>{esc(fig['title'])}</title>",
        f'<rect width="{W}" height="{h}" fill="{WHITE}"/>',
        f'<rect x="{PAD_L}" y="36" width="5" height="30" rx="2.5" fill="{C_ACCENT}"/>',
        text(PAD_L + 18, 58, fig["title"], size=28, fill=C_TEXT, weight=700),
        text(PAD_L + 18, 88, fig["subtitle"], size=13.5, fill=C_SUB),
    ]

    for i, (label, val) in enumerate(items):
        y = HBAR_TOP + i * HBAR_GAP
        cy = y + HBAR_H / 2
        bar_w = round(val / vmax * HBAR_FULL, 1)
        parts.append(
            f'<rect x="{HBAR_X}" y="{y}" width="{HBAR_FULL}" height="{HBAR_H}" rx="8" fill="{C_TRACK}"/>'
        )
        parts.append(
            f'<rect x="{HBAR_X}" y="{y}" width="{bar_w:g}" height="{HBAR_H}" rx="8" fill="{C_ACCENT}"/>'
        )
        parts.append(text(HBAR_LABEL_RIGHT, cy + 6, label, size=17, fill=C_TEXT, anchor="end"))
        parts.append(
            text(HBAR_X + bar_w - 18, cy + 6.5, f"{val:.2f}%", size=18, fill=WHITE, weight=700, anchor="end")
        )

    parts.append(
        f'<line x1="{PAD_L}" y1="{line_y}" x2="{W - 60}" y2="{line_y}" stroke="{C_LINE}" stroke-width="1"/>'
    )
    parts.append(text(PAD_L, foot_y, fig["source"], size=13, fill=C_SUB))
    return wrap(parts, W, h), W, h


# ============================================================
# 渲染器：状态流转 + 流程条
# ============================================================

FLOW_STATE_W = 200
FLOW_STATE_H = 88
FLOW_STATE_Y = 64
FLOW_STEP_W = 173
FLOW_STEP_H = 76
FLOW_STEP_Y = 262

_TONES = {
    "muted": (C_TRACK, C_SUB, None),
    "primary": (C_ACCENT, WHITE, None),
    "soft": (C_SOFT, C_DEEP, C_ACCENT),
}


def render_flow(fig: dict) -> tuple[str, int, int]:
    h = 384
    parts = [f'<rect width="{W}" height="{h}" fill="{WHITE}"/>']
    parts.append(text(PAD_L, 40, fig["state_title"], size=13.5, fill=C_SUB))

    # 状态框：三等分，中间留出箭头通道
    states = fig["states"]
    span, gap = 110, 70
    box_w = (W - 2 * gap - (len(states) - 1) * span) / len(states)
    cy = FLOW_STATE_Y + FLOW_STATE_H / 2

    for i, st in enumerate(states):
        x = gap + i * (box_w + span)
        fill, fg, stroke = _TONES[st["tone"]]
        border = f' stroke="{stroke}" stroke-width="1.5"' if stroke else ""
        parts.append(
            f'<rect x="{x:g}" y="{FLOW_STATE_Y}" width="{box_w:g}" height="{FLOW_STATE_H}" '
            f'rx="12" fill="{fill}"{border}/>'
        )
        parts.append(text(x + box_w / 2, cy - 4, st["key"], size=17, fill=fg, weight=700, anchor="middle"))
        parts.append(text(x + box_w / 2, cy + 22, st["cn"], size=14, fill=fg, anchor="middle"))
        if i < len(states) - 1:
            x1, x2 = x + box_w, x + box_w + span
            parts.append(arrow(x1 + 10, x2 - 10, cy))
            parts.append(
                lines((x1 + x2) / 2, cy + 34, fig["edges"][i], size=12, fill=C_SUB, anchor="middle", lh=15)
            )

    parts.append(text(PAD_L, 182, fig["state_note"], size=12, fill=C_SUB))

    # 流程条
    parts.append(text(PAD_L, 244, fig["step_title"], size=13.5, fill=C_SUB))
    steps = fig["steps"]
    s_gap = 56
    s_w = (W - 2 * 70 - (len(steps) - 1) * s_gap) / len(steps)
    for i, s in enumerate(steps):
        x = 70 + i * (s_w + s_gap)
        last = i == len(steps) - 1
        fill, fg = (C_ACCENT, WHITE) if last else (C_SOFT, C_DEEP)
        parts.append(
            f'<rect x="{x:g}" y="{FLOW_STEP_Y}" width="{s_w:g}" height="{FLOW_STEP_H}" '
            f'rx="10" fill="{fill}"/>'
        )
        body = s.split("\n")
        y0 = FLOW_STEP_Y + FLOW_STEP_H / 2 - (len(body) - 1) * 10 + 6
        parts.append(lines(x + s_w / 2, y0, s, size=14, fill=fg, weight=700, anchor="middle", lh=22))
        if not last:
            parts.append(arrow(x + s_w + 8, x + s_w + s_gap - 8, FLOW_STEP_Y + FLOW_STEP_H / 2, width=2.2, head=8))

    return wrap(parts, W, h), W, h


# ============================================================
# 渲染器：百分比堆叠条形图
# ============================================================

ST_LABEL_RIGHT = 160
ST_X = 180
ST_FULL = 760
ST_H = 38
ST_ROW = 56
ST_TOP = 90


def render_stacked(fig: dict) -> tuple[str, int, int]:
    rows = fig["rows"]
    dims = fig["dims"]
    bar_bottom = ST_TOP + (len(rows) - 1) * ST_ROW + ST_H
    foot_y = bar_bottom + 46
    h = foot_y + 20

    parts = [f'<rect width="{W}" height="{h}" fill="{WHITE}"/>']

    # 图例：整体居中
    units = [(14 + 6 + len(name) * 12.5) for name, _ in dims]
    total = sum(units) + 28 * (len(dims) - 1)
    x = (W - total) / 2
    for (name, color), uw in zip(dims, units):
        parts.append(f'<rect x="{x:.1f}" y="36" width="14" height="14" rx="3" fill="{color}"/>')
        parts.append(text(x + 20, 48, name, size=12.5, fill=C_TEXT))
        x += uw + 28

    for i, (label, weights) in enumerate(rows):
        y = ST_TOP + i * ST_ROW
        cy = y + ST_H / 2
        parts.append(text(ST_LABEL_RIGHT, cy + 5, label, size=14, fill=C_TEXT, anchor="end"))
        # 整条裁成圆角：色块本身是直角矩形，靠裁剪路径收边
        parts.append(
            f'<clipPath id="st{i}"><rect x="{ST_X}" y="{y}" width="{ST_FULL}" '
            f'height="{ST_H}" rx="6"/></clipPath>'
        )
        parts.append(f'<g clip-path="url(#st{i})">')
        x = ST_X
        for (name, color), val in zip(dims, weights):
            seg = val / 100 * ST_FULL
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{seg:.1f}" height="{ST_H}" fill="{color}"/>'
            )
            # 深色段用白字，浅色段用深字，保证两端的对比度
            fg = WHITE if color in ("#3a54d6", "#5b78f0") else C_TEXT
            parts.append(
                text(x + seg / 2, cy + 5, str(val), size=13, fill=fg, weight=700, anchor="middle")
            )
            x += seg
        parts.append("</g>")
        parts.append(
            f'<rect x="{ST_X}" y="{y}" width="{ST_FULL}" height="{ST_H}" rx="6" fill="none" '
            f'stroke="{C_LINE}" stroke-width="1"/>'
        )

    parts.append(text(PAD_L, foot_y, fig["note"], size=12.5, fill=C_SUB))
    return wrap(parts, W, h), W, h


# ============================================================
# 渲染器：并列卡片栏
# ============================================================

COL_W = 253
COL_H = 280
COL_Y = 60
COL_GAP = 60
COL_HEAD = 48


def render_columns(fig: dict) -> tuple[str, int, int]:
    cols = fig["columns"]
    h = COL_Y + COL_H + 50
    total = len(cols) * COL_W + (len(cols) - 1) * COL_GAP
    left = (W - total) / 2
    parts = [f'<rect width="{W}" height="{h}" fill="{WHITE}"/>']

    for i, col in enumerate(cols):
        x = left + i * (COL_W + COL_GAP)
        parts.append(
            f'<rect x="{x:g}" y="{COL_Y}" width="{COL_W}" height="{COL_H}" rx="12" '
            f'fill="{WHITE}" stroke="{C_LINE}" stroke-width="1.5"/>'
        )
        # 顶部标题条：用裁剪路径做出上圆角
        parts.append(
            f'<clipPath id="c{i}"><rect x="{x:g}" y="{COL_Y}" width="{COL_W}" '
            f'height="{COL_HEAD}" rx="12"/></clipPath>'
        )
        parts.append(
            f'<rect x="{x:g}" y="{COL_Y}" width="{COL_W}" height="{COL_HEAD}" '
            f'fill="{C_ACCENT}" clip-path="url(#c{i})"/>'
        )
        parts.append(
            text(x + COL_W / 2, COL_Y + 31, col["title"], size=17, fill=WHITE, weight=700, anchor="middle")
        )
        for j, item in enumerate(col["items"]):
            iy = COL_Y + COL_HEAD + 34 + j * 56
            parts.append(f'<circle cx="{x + 22:g}" cy="{iy - 4:g}" r="3.2" fill="{C_ACCENT}"/>')
            parts.append(text(x + 34, iy, item, size=12.5, fill=C_TEXT))

        if i < len(cols) - 1:
            parts.append(arrow(x + COL_W + 12, x + COL_W + COL_GAP - 12, COL_Y + COL_H / 2, width=2.2, head=8))

    return wrap(parts, W, h), W, h


# ============================================================
# 渲染器：开关分叉（一个配置项分出两条并列路径，再汇入共同约定）
# ============================================================

BR_SWITCH = (620, 78, 40)     # 宽、高、顶
BR_CARD = (360, 220, 196)     # 宽、高、顶
BR_FOOT = (700, 74, 476)      # 宽、高、顶
BR_RAIL_Y = 152               # 分叉横线
BR_MERGE_Y = 444              # 汇聚横线


def render_branch(fig: dict) -> tuple[str, int, int]:
    h = 590
    cx = W / 2
    cs = [W / 4 + 30, W * 3 / 4 - 30]      # 两条链路的中心线
    sw, sh, sy = BR_SWITCH
    cw, ch, cy0 = BR_CARD
    fw, fh, fy = BR_FOOT
    parts = [f'<rect width="{W}" height="{h}" fill="{WHITE}"/>']

    # 配置项
    parts.append(
        f'<rect x="{(W - sw) / 2:g}" y="{sy}" width="{sw}" height="{sh}" rx="12" '
        f'fill="{WHITE}" stroke="{C_ACCENT}" stroke-width="2"/>'
    )
    parts.append(text(cx, sy + 34, fig["switch"]["title"], size=18, fill=C_DEEP, weight=700, anchor="middle"))
    parts.append(text(cx, sy + 60, fig["switch"]["sub"], size=12.5, fill=C_SUB, anchor="middle"))

    # 分叉：先共用一段竖线，再各自转横、落下箭头
    for c in cs:
        parts.append(rail(cx, c, (sy + sh, BR_RAIL_Y)))
        parts.append(v_arrow(c, BR_RAIL_Y, cy0 - 10))
    for c, br in zip(cs, fig["branches"]):
        parts.append(
            text((cx + c) / 2, BR_RAIL_Y - 8, br["label"], size=14, fill=C_DEEP, weight=700, anchor="middle")
        )

    # 两条链路
    for c, br in zip(cs, fig["branches"]):
        x = c - cw / 2
        parts.append(
            f'<rect x="{x:g}" y="{cy0}" width="{cw}" height="{ch}" rx="12" '
            f'fill="{WHITE}" stroke="{C_LINE}" stroke-width="1.5"/>'
        )
        parts.append(text(c, cy0 + 38, br["title"], size=17, fill=C_TEXT, weight=700, anchor="middle"))
        parts.append(text(c, cy0 + 64, br["sub"], size=14, fill=C_ACCENT, weight=700, anchor="middle"))
        parts.append(
            f'<line x1="{x + 28:g}" y1="{cy0 + 84}" x2="{x + cw - 28:g}" y2="{cy0 + 84}" '
            f'stroke="{C_LINE}" stroke-width="1"/>'
        )
        for j, item in enumerate(br["items"]):
            iy = cy0 + 112 + j * 44
            parts.append(f'<circle cx="{x + 30:g}" cy="{iy - 4:g}" r="3.2" fill="{C_ACCENT}"/>')
            parts.append(text(x + 42, iy, item, size=12.5, fill=C_TEXT))

    # 汇聚到共同约定
    for c in cs:
        parts.append(
            f'<path d="M {c:g} {cy0 + ch} V {BR_MERGE_Y} H {cx:g}" fill="none" '
            f'stroke="{C_ACCENT}" stroke-width="2.4" stroke-linejoin="round"/>'
        )
    parts.append(v_arrow(cx, BR_MERGE_Y, fy - 8))

    parts.append(
        f'<rect x="{(W - fw) / 2:g}" y="{fy}" width="{fw}" height="{fh}" rx="12" fill="{C_SOFT}"/>'
    )
    parts.append(text(cx, fy + 32, fig["footer"]["title"], size=15, fill=C_DEEP, weight=700, anchor="middle"))
    parts.append(text(cx, fy + 56, fig["footer"]["sub"], size=12.5, fill=C_SUB, anchor="middle"))

    return wrap(parts, W, h), W, h


# ============================================================
# 渲染器：项目实施甘特图
# ============================================================

GANTT_LABEL_R = 196      # 行名右对齐位置
GANTT_X = 210            # 条区左端
GANTT_R = 960            # 条区右端
GANTT_PHASE_Y = 104      # 阶段色带首行顶部
GANTT_PHASE_H = 34       # 阶段色带高度
GANTT_TOP = 224          # 模块首行条顶
GANTT_ROW_H = 42         # 行距
GANTT_BAR_H = 26         # 条高

# 阶段色带的（底色, 文字色, 描边色）；末档浅底描边，示意与其他阶段并行
GANTT_TONES = [
    (C_TRACK, C_SUB, None),
    (C_ACCENT, WHITE, None),
    (C_DEEP, WHITE, None),
    (C_SOFT, C_DEEP, C_ACCENT),
]


def render_gantt(fig: dict) -> tuple[str, int, int]:
    """项目实施甘特图：上方阶段色带（可两行错开表示并行），下方各模块工作区间。"""
    d0 = date.fromisoformat(fig["date_start"])
    d1 = date.fromisoformat(fig["date_end"])

    def x_of(ds: str) -> float:
        return GANTT_X + (date.fromisoformat(ds) - d0).days / (d1 - d0).days * (GANTT_R - GANTT_X)

    rows = fig["rows"]
    bar_bottom = GANTT_TOP + (len(rows) - 1) * GANTT_ROW_H + GANTT_BAR_H
    grid_top = GANTT_PHASE_Y + 2 * (GANTT_PHASE_H + 6) + 26
    foot_y = bar_bottom + 52
    h = foot_y + 24

    parts = [
        f"<title>{esc(fig['title'])}</title>",
        f'<rect width="{W}" height="{h}" fill="{WHITE}"/>',
        f'<rect x="{PAD_L}" y="36" width="5" height="30" rx="2.5" fill="{C_ACCENT}"/>',
        text(PAD_L + 18, 58, fig["title"], size=28, fill=C_TEXT, weight=700),
        text(PAD_L + 18, 88, fig["subtitle"], size=13.5, fill=C_SUB),
    ]

    for ph in fig["phases"]:
        x1 = PAD_L if ph.get("open_left") else x_of(ph["start"])
        x2 = x_of(ph["end"])
        y = GANTT_PHASE_Y + ph["row"] * (GANTT_PHASE_H + 6)
        fill, fg, stroke = GANTT_TONES[ph["tone"]]
        edge = f' stroke="{stroke}" stroke-width="1.5" stroke-dasharray="5 4"' if stroke else ""
        parts.append(
            f'<rect x="{x1 + 1.5:g}" y="{y}" width="{x2 - x1 - 3:g}" height="{GANTT_PHASE_H}" '
            f'rx="7" fill="{fill}"{edge}/>'
        )
        parts.append(text((x1 + x2) / 2, y + 22, ph["name"], size=11.5, fill=fg, weight=600, anchor="middle"))

    for tk in fig["ticks"]:
        x = x_of(tk)
        parts.append(
            f'<line x1="{x:g}" y1="{grid_top}" x2="{x:g}" y2="{bar_bottom}" '
            f'stroke="{C_TRACK}" stroke-width="1"/>'
        )
        parts.append(text(x, grid_top - 8, tk[5:], size=12, fill=C_SUB, anchor="middle"))

    for i, r in enumerate(rows):
        y = GANTT_TOP + i * GANTT_ROW_H
        x1, x2 = x_of(r["start"]), x_of(r["end"])
        parts.append(text(GANTT_LABEL_R, y + 18, r["name"], size=14.5, fill=C_TEXT, anchor="end"))
        parts.append(
            f'<rect x="{x1:g}" y="{y}" width="{x2 - x1:g}" height="{GANTT_BAR_H}" rx="6" fill="{C_ACCENT}"/>'
        )
        parts.append(text(x1 + 10, y + 17.5, f'{r["start"][5:]} ~ {r["end"][5:]}', size=11.5, fill=WHITE))

    parts.append(
        f'<line x1="{PAD_L}" y1="{foot_y - 26}" x2="{W - 40}" y2="{foot_y - 26}" stroke="{C_LINE}"/>'
    )
    parts.append(text(PAD_L, foot_y, fig["source"], size=12.5, fill=C_SUB))
    return wrap(parts, W, h), W, h


# ============================================================
# 渲染分派与导出
# ============================================================

RENDERERS = {
    "hbar": render_hbar,
    "flow": render_flow,
    "stacked": render_stacked,
    "columns": render_columns,
    "branch": render_branch,
    "gantt": render_gantt,
}


def render_svg(fig: dict) -> tuple[str, int, int]:
    kind = fig.get("type", "hbar")
    if kind not in RENDERERS:
        raise ValueError(f"未知的图形类型：{kind}（可用：{'、'.join(RENDERERS)}）")
    return RENDERERS[kind](fig)


def find_browser() -> str | None:
    """找一个可用的 Chromium 系浏览器，用于渲染 PNG。"""
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def svg_to_png(browser: str, svg_path: Path, png_path: Path, w: int, h: int) -> None:
    """借浏览器把 SVG 渲染成位图。

    中间产物一律走 ASCII 临时目录，避开 Chromium 对非 ASCII 参数的转码问题。
    """
    pw, ph = w * PNG_SCALE, h * PNG_SCALE
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wrap_html = tmp / "wrap.html"
        wrap_html.write_text(
            '<!doctype html><html><head><meta charset="utf-8"><style>'
            "html,body{margin:0;padding:0;background:#fff}"
            f"img{{display:block;width:{pw}px;height:{ph}px}}"
            "</style></head><body>"
            f'<img src="{svg_path.as_uri()}"></body></html>',
            encoding="utf-8",
        )
        shot = tmp / "out.png"
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--default-background-color=FFFFFFFF",
            f"--window-size={pw},{ph}",
            f"--screenshot={shot}",
            wrap_html.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        if not shot.exists():
            raise RuntimeError(
                f"浏览器未产出图片（退出码 {proc.returncode}）：\n"
                + proc.stderr.decode("utf-8", "replace")[-1500:]
            )
        shutil.move(str(shot), str(png_path))


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else ""
    browser = find_browser()
    if not browser:
        print("找不到 Chrome 或 Edge，只能出 SVG。")
    else:
        print(f"浏览器：{browser}")

    for fig in FIGURES:
        if keyword and keyword not in fig["file"]:
            continue
        svg, w, h = render_svg(fig)
        svg_path = HERE / f"{fig['file']}.svg"
        svg_path.write_text(svg, encoding="utf-8")
        print(f"SVG  {svg_path.name}  ({w}x{h})")

        if browser:
            png_path = HERE / f"{fig['file']}.png"
            svg_to_png(browser, svg_path, png_path, w, h)
            print(f"PNG  {png_path.name}  ({w * PNG_SCALE}x{h * PNG_SCALE}, {png_path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
