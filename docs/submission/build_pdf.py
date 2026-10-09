# -*- coding: utf-8 -*-
"""把提交材料 Markdown 排成 A4 PDF。

流程：pandoc 把 Markdown 转成 HTML，套上排版样式与内嵌插图，
再由本机 Chrome 无头模式打印成 PDF，不引入第三方 Python 依赖。

文中形如
    [图2-1：说明文字　配图：`figures/fig-2-1-xxx.png`]
的占位行会替换成真实插图（base64 内嵌，成品 PDF 不依赖图片文件路径）。

用法：
    python build_pdf.py 05-项目的详细分工及过程.md
    python build_pdf.py 05-项目的详细分工及过程.md -o 输出.pdf
"""

from __future__ import annotations

import base64
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent

# ============================================================
# 版式（A4 正文，配色与 figures/ 出图脚本同源）
# ============================================================

PAGE_CSS = """
@page { size: A4; margin: 19mm 17mm 17mm; }

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }

body {
  font-family: "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif;
  font-size: 10.5pt;
  line-height: 1.8;
  color: #1f2430;
  margin: 0;
}

h1 {
  font-size: 20pt;
  font-weight: 700;
  text-align: center;
  margin: 0 0 9mm;
  letter-spacing: 1px;
}

h2 {
  font-size: 15pt;
  margin: 9mm 0 4mm;
  padding-left: 3.5mm;
  border-left: 3px solid #4f6ef7;
  break-after: avoid;
}

h3 {
  font-size: 12.5pt;
  margin: 7mm 0 3mm;
  color: #2a3450;
  break-after: avoid;
}

h4 {
  font-size: 11.5pt;
  margin: 5.5mm 0 2.5mm;
  color: #2a3450;
  break-after: avoid;
}

p { margin: 0 0 3mm; text-align: justify; }

/* 表格标题（整段只有一个加粗）居中 */
p:has(> strong:only-child) { text-align: center; margin: 5mm 0 2.5mm; }

table {
  border-collapse: collapse;
  width: 100%;
  font-size: 9.5pt;
  line-height: 1.6;
  margin: 0 0 5mm;
}

thead { display: table-header-group; }
tr { break-inside: avoid; }

th, td {
  border: 0.6pt solid #c9d0e0;
  padding: 1.6mm 2.4mm;
  text-align: left;
  vertical-align: top;
}

th { background: #eef1ff; color: #2a3450; font-weight: 600; }

tbody tr:nth-child(even) { background: #fafbff; }

blockquote {
  margin: 4mm 0;
  padding: 2.5mm 4mm;
  background: #f7f8fc;
  border-left: 3px solid #b9c4e8;
  color: #3a4660;
  font-size: 10pt;
}

blockquote p { margin: 0 0 1.5mm; }
blockquote p:last-child { margin-bottom: 0; }

code {
  font-family: Consolas, "Courier New", monospace;
  font-size: 9pt;
  background: #f0f2f8;
  padding: 0.3mm 1mm;
  border-radius: 2px;
  color: #3a54d6;
}

figure.fig {
  margin: 5mm 0 6mm;
  text-align: center;
  break-inside: avoid;
}

figure.fig img { max-width: 100%; max-height: 112mm; border: 0.6pt solid #e4e8f2; }

figure.fig figcaption {
  margin-top: 2mm;
  font-size: 9.5pt;
  color: #7a8296;
}

hr { border: none; border-top: 0.6pt solid #dfe3ee; margin: 7mm 0; }
"""

TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""

# 图占位行：[图2-1：说明　配图：`figures/xxx.png`]
FIG_RE = re.compile(
    r"^\[(?P<cap>图\s*\d+-\d+：[^　\]]+)\u3000配图：`(?P<path>[^`]+)`\]$",
    re.M,
)


def embed_figures(md: str) -> str:
    """把图占位行换成 base64 内嵌的插图；图片缺失时保留原文以便排查。"""
    def repl(m: re.Match) -> str:
        path = HERE / m.group("path")
        if not path.exists():
            print(f"警告：图片不存在，保留占位 {path}")
            return m.group(0)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        label = m.group("cap").replace("：", "\u3000")
        return (
            f'<figure class="fig">'
            f'<img src="data:{mime};base64,{data}" alt="{label}">'
            f"<figcaption>{label}</figcaption>"
            f"</figure>"
        )

    return FIG_RE.sub(repl, md)


def stamp_page_numbers(pdf_path: Path) -> None:
    """在每页底部居中盖上页码。

    Chrome 命令行打印不支持 CSS 页码，生成后用 pymupdf 补（未装则跳过）。
    """
    try:
        import pymupdf
    except ImportError:
        print("提示：未安装 pymupdf，跳过页码。")
        return
    doc = pymupdf.open(str(pdf_path))
    for i, page in enumerate(doc):
        r = page.rect
        page.insert_text(
            pymupdf.Point(r.width / 2 - 5, r.height - 26),
            str(i + 1), fontsize=9, fontname="helv", color=(0.55, 0.58, 0.64),
        )
    doc.saveIncr()


def find_pandoc() -> str | None:
    for name in ("pandoc", "pandoc.exe"):
        found = shutil.which(name)
        if found:
            return found
    for cand in (r"F:\Anaconda3\Library\bin\pandoc.exe",):
        if Path(cand).exists():
            return cand
    return None


def find_browser() -> str | None:
    """找一个可用的 Chromium 系浏览器，用于打印 PDF。"""
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


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1

    src = Path(argv[0])
    if not src.is_absolute():
        src = HERE / src
    if not src.exists():
        print(f"找不到源文件：{src}")
        return 1

    dst = Path(argv[argv.index("-o") + 1]) if "-o" in argv else src.with_suffix(".pdf")
    if not dst.is_absolute():
        dst = HERE / dst

    pandoc, browser = find_pandoc(), find_browser()
    if not pandoc:
        print("找不到 pandoc（可装 pandoc 或改用其他转换工具）。")
        return 1
    if not browser:
        print("找不到 Chrome 或 Edge，无法打印 PDF。")
        return 1

    md = embed_figures(src.read_text(encoding="utf-8"))

    # 中间产物一律走 ASCII 临时目录，避开 Chromium 对非 ASCII 参数的转码问题
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        md_path, body_path = tmp / "doc.md", tmp / "body.html"
        html_path, pdf_path = tmp / "doc.html", tmp / "out.pdf"

        md_path.write_text(md, encoding="utf-8")
        subprocess.run(
            [pandoc, str(md_path), "-f", "gfm", "-t", "html5", "-o", str(body_path)],
            check=True,
            capture_output=True,
        )
        html_path.write_text(
            TEMPLATE.format(
                title=src.stem, css=PAGE_CSS,
                body=body_path.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ],
            capture_output=True,
            timeout=180,
        )
        if not pdf_path.exists():
            print("浏览器未产出 PDF：\n" + proc.stderr.decode("utf-8", "replace")[-1500:])
            return 1
        shutil.move(str(pdf_path), str(dst))

    stamp_page_numbers(dst)
    print(f"PDF  {dst.name}  ({dst.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
