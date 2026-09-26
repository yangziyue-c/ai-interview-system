# -*- coding: utf-8 -*-
"""生成《项目简介 PPT》的插图，SVG 与 PNG 各出一份。

SVG 由字符串拼装，PNG 交给本机 Chrome 或 Edge 的无头模式渲染，不引入第三方依赖。
改脚本顶部的 FIGURES 即可重出；新增一张图就再加一个配置字典。

用法：
    python build_figures.py            # 全部重出
    python build_figures.py fig-1-2    # 只重出名字里含该串的图
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent

# ============================================================
# 数据与文案
# ============================================================

FIGURES = [
    {
        "file": "fig-1-2-求职失败主要原因",
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
]

# ============================================================
# 版式与配色（色值与演示前端 frontend_test/css/style.css 同源）
# ============================================================

FONT = "'Microsoft YaHei','PingFang SC','Hiragino Sans GB',sans-serif"

C_TEXT = "#1f2430"     # 正文
C_SUB = "#7a8296"      # 次要文字
C_LINE = "#e4e8f2"     # 分隔线
C_TRACK = "#f2f4fa"    # 柱底轨道
C_ACCENT = "#4f6ef7"   # 主题蓝

W = 1000               # 画布宽（逻辑像素）
PAD_L = 44             # 左边距
LABEL_RIGHT = 170      # 项名右对齐位置
BAR_X = 190            # 柱区左端
BAR_FULL = 750         # 满量程宽度，最大项占满
BAR_H = 58             # 柱高
ROW_GAP = 86           # 行距
BAR_TOP = 140          # 首行柱顶

PNG_SCALE = 3          # PNG 相对逻辑尺寸的倍数，3 倍约合 300 DPI


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


def render_svg(fig: dict) -> tuple[str, int, int]:
    """渲染一张横向柱状图，返回 (SVG 文本, 宽, 高)。"""
    items = fig["items"]
    vmax = max(v for _, v in items) * fig.get("headroom", 1.0)

    bar_bottom = BAR_TOP + (len(items) - 1) * ROW_GAP + BAR_H
    line_y = bar_bottom + 46
    foot_y = line_y + 30
    h = foot_y + 22

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}">',
        f"<title>{esc(fig['title'])}</title>",
        f'<rect width="{W}" height="{h}" fill="#ffffff"/>',
        # 标题与其左侧装饰条
        f'<rect x="{PAD_L}" y="36" width="5" height="30" rx="2.5" fill="{C_ACCENT}"/>',
        text(PAD_L + 18, 58, fig["title"], size=28, fill=C_TEXT, weight=700),
        text(PAD_L + 18, 88, fig["subtitle"], size=13.5, fill=C_SUB),
    ]

    for i, (label, val) in enumerate(items):
        y = BAR_TOP + i * ROW_GAP
        cy = y + BAR_H / 2
        bar_w = round(val / vmax * BAR_FULL, 1)
        parts.append(
            f'<rect x="{BAR_X}" y="{y}" width="{BAR_FULL}" height="{BAR_H}" rx="8" fill="{C_TRACK}"/>'
        )
        parts.append(
            f'<rect x="{BAR_X}" y="{y}" width="{bar_w:g}" height="{BAR_H}" rx="8" fill="{C_ACCENT}"/>'
        )
        parts.append(text(LABEL_RIGHT, cy + 6, label, size=17, fill=C_TEXT, anchor="end"))
        parts.append(
            text(BAR_X + bar_w - 18, cy + 6.5, f"{val:.2f}%", size=18, fill="#ffffff", weight=700, anchor="end")
        )

    parts.append(
        f'<line x1="{PAD_L}" y1="{line_y}" x2="{W - 60}" y2="{line_y}" stroke="{C_LINE}" stroke-width="1"/>'
    )
    parts.append(text(PAD_L, foot_y, fig["source"], size=13, fill=C_SUB))
    parts.append("</svg>")

    return "\n".join(parts) + "\n", W, h


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
        wrap = tmp / "wrap.html"
        wrap.write_text(
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
            wrap.as_uri(),
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
