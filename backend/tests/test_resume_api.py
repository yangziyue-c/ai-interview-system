"""简历导入接口测试

**PDF 夹具是手工构造的结构完全合法的 PDF**（算准 xref 字节偏移，每行恰好 20 字节）：
不引入 reportlab/fpdf 等新依赖（本项目对依赖极克制），也不写「没有 xref 的残缺 PDF」
——后者只能靠 pypdf 的容错路径读取，而该行为随版本变动，测试会变成「测 pypdf 的宽容度」
而不是「测我们的代码」。

**夹具只放 ASCII**：Type1 标准字体用 WinAnsi 编码，塞中文会被 pypdf 的解码器毁掉。
中文的抽取规则由 tests/test_resume_fields.py 用纯函数直接喂字符串覆盖——接口测管道
（字节 → 文本 → 落库 → 响应），纯函数测中文启发式。
"""
import time
from pathlib import Path

from httpx import AsyncClient

from app.config import settings
from tests.test_api import _PNG_1PX, _register

BASE = "/api/v1"


def _pdf_literal(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def make_text_pdf(lines: list[str]) -> bytes:
    """构造含文本层的最小合法 PDF（单页 / Helvetica / 仅 ASCII）"""
    body = b"BT /F1 12 Tf 72 720 Td 14 TL\n"
    for line in lines:
        body += b"(" + _pdf_literal(line) + b") Tj T*\n"
    body += b"ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()  # 每行必须恰好 20 字节
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


_PDF_BASIC = make_text_pdf(
    ["Name: Zhang San", "Student ID: 20210001", "Target Position: Backend Engineer"]
)
_PDF_NO_TEXT = make_text_pdf([])
_PDF_BROKEN = b"%PDF-1.4\nthis is not a real pdf body"


async def _upload(
    client: AsyncClient,
    headers: dict,
    name: str = "resume.pdf",
    content: bytes | None = None,
    mime: str = "application/pdf",
):
    return await client.post(
        f"{BASE}/resumes",
        files={"file": (name, _PDF_BASIC if content is None else content, mime)},
        headers=headers,
    )


class TestResumeUpload:
    async def test_upload_pdf_extracts_fields(self, client: AsyncClient):
        """主路径：PDF 落盘 + 提取 + 三个字段都给出建议"""
        _, headers = await _register(client, "resume")
        resp = await _upload(client, headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]

        assert data["parse_status"] == "parsed"
        assert data["file_ext"] == ".pdf"
        assert data["file_size"] == len(_PDF_BASIC)
        assert data["text_truncated"] is False
        assert "Student ID" in data["text"]
        assert data["suggested"] == {
            "nickname": "Zhang San",
            "student_id": "20210001",
            "target_position": "backend",
        }
        # 建议必须带来源说明，用户才知道凭什么预填
        assert data["suggested_notes"]["student_id"]

    async def test_upload_image_is_pending_not_fake(self, client: AsyncClient):
        """图片：接受上传，但明说未识别，不假装成功"""
        _, headers = await _register(client, "img")
        resp = await _upload(client, headers, "photo.png", _PNG_1PX, "image/png")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["parse_status"] == "image_pending"
        assert "手动填写" in data["parse_message"]
        assert data["text"] is None
        assert data["suggested"] == {
            "nickname": None,
            "student_id": None,
            "target_position": None,
        }

    async def test_upload_pdf_without_text_layer(self, client: AsyncClient):
        """扫描件式 PDF：打开成功但没有文字层"""
        _, headers = await _register(client, "scan")
        resp = await _upload(client, headers, "scan.pdf", _PDF_NO_TEXT)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["parse_status"] == "no_text_layer"
        assert data["text"] is None
        assert data["suggested"]["nickname"] is None

    async def test_upload_corrupt_pdf_does_not_500(self, client: AsyncClient):
        """残缺 PDF 不能打成 500，也不能误抽字段

        只断言状态属于 {failed, no_text_layer} 而不钉死某一个：pypdf 对残缺文件是抛异常
        还是返回空内容，随版本而变，钉死会让这条用例锁住库的行为而不是我们的行为。
        """
        _, headers = await _register(client, "broken")
        resp = await _upload(client, headers, "broken.pdf", _PDF_BROKEN)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["parse_status"] in {"failed", "no_text_layer"}
        assert data["suggested"]["student_id"] is None

    async def test_upload_garbled_pdf(self, client: AsyncClient, monkeypatch):
        """字体缺 ToUnicode 的 PDF：判为乱码并引导手填"""
        _, headers = await _register(client, "garbled")
        monkeypatch.setattr(
            "app.adapters.resume_parser._extract_pdf_text",
            lambda content: "(cid:12)(cid:34)(cid:56)",
        )
        resp = await _upload(client, headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["parse_status"] == "garbled"

    async def test_upload_parse_timeout_degrades(self, client: AsyncClient, monkeypatch):
        """解析超时降级为 failed——不能让请求挂死（超时只让请求返回，线程仍在跑）"""
        _, headers = await _register(client, "slow")
        monkeypatch.setattr(settings, "RESUME_PARSE_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(
            "app.adapters.resume_parser._extract_pdf_text",
            lambda content: time.sleep(0.4) or "纯文本",
        )
        resp = await _upload(client, headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["parse_status"] == "failed"
        assert "超时" in resp.json()["data"]["parse_message"]

    async def test_upload_rejects_bad_extension(self, client: AsyncClient):
        _, headers = await _register(client, "badext")
        resp = await _upload(client, headers, "resume.docx", b"PK\x03\x04", "application/msword")
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

    async def test_upload_rejects_fake_pdf(self, client: AsyncClient):
        """把 HTML 改名成 .pdf：文件头校验挡住"""
        _, headers = await _register(client, "fake")
        resp = await _upload(
            client, headers, "evil.pdf", b"<html><script>alert(1)</script>"
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

    async def test_upload_rejects_too_large(self, client: AsyncClient):
        _, headers = await _register(client, "big")
        too_big = b"%PDF-" + b"\x00" * (settings.MAX_RESUME_SIZE_MB * 1024 * 1024)
        resp = await _upload(client, headers, "big.pdf", too_big)
        assert resp.status_code == 400
        assert resp.json()["code"] == 40000

    async def test_upload_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/resumes", files={"file": ("a.pdf", _PDF_BASIC, "application/pdf")}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100

    async def test_upload_truncates_long_text(self, client: AsyncClient):
        """超长文本按上限截断，text_length 保留截断前的长度供前端提示"""
        _, headers = await _register(client, "long")
        resp = await _upload(client, headers, "long.pdf", make_text_pdf(["A" * 12000]))
        data = resp.json()["data"]
        assert len(data["text"]) == settings.MAX_RESUME_TEXT_CHARS
        assert data["text_truncated"] is True
        assert data["text_length"] > settings.MAX_RESUME_TEXT_CHARS

    async def test_upload_stores_in_private_dir_not_public(self, client: AsyncClient):
        """安全断言：原件落在私有目录，公开挂载点取不到，响应也不泄露磁盘路径"""
        _, headers = await _register(client, "private")
        resp = await _upload(client, headers)
        assert resp.status_code == 200

        files = list(Path(settings.RESUME_DIR).glob("*"))
        assert files, "简历原件没有落盘到私有目录"
        # /uploads 是公开静态挂载，简历绝不能出现在那里
        assert (await client.get(f"/uploads/{files[0].name}")).status_code == 404
        # 响应里不得出现磁盘路径或内部文件名
        assert "stored_name" not in resp.json()["data"]
        assert str(settings.RESUME_DIR) not in resp.text


class TestResumeRead:
    async def test_latest_is_null_before_upload(self, client: AsyncClient):
        """空态是 200 + null，不是 404（空态查询而非缺资源）"""
        _, headers = await _register(client, "empty")
        resp = await client.get(f"{BASE}/resumes/latest", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"] is None

    async def test_latest_returns_newest(self, client: AsyncClient):
        _, headers = await _register(client, "newest")
        await _upload(client, headers, "first.pdf")
        await _upload(client, headers, "second.pdf")
        data = (await client.get(f"{BASE}/resumes/latest", headers=headers)).json()["data"]
        assert data["original_filename"] == "second.pdf"

    async def test_latest_before_id_route(self, client: AsyncClient):
        """/latest 不能被 /{resume_id} 抢走——抢走会因 int 转换失败变成 422"""
        _, headers = await _register(client, "route")
        assert (await client.get(f"{BASE}/resumes/latest", headers=headers)).status_code == 200

    async def test_other_user_cannot_see_it(self, client: AsyncClient):
        _, headers_a = await _register(client, "ownera")
        _, headers_b = await _register(client, "ownerb")
        await _upload(client, headers_a)
        resp = await client.get(f"{BASE}/resumes/latest", headers=headers_b)
        assert resp.json()["data"] is None

    async def test_latest_requires_auth(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/resumes/latest")
        assert resp.status_code == 401


class TestResumeDownload:
    async def test_download_own_file_bytes_equal(self, client: AsyncClient):
        """下载回来的字节必须与上传的完全一致"""
        _, headers = await _register(client, "dl")
        resume_id = (await _upload(client, headers)).json()["data"]["id"]
        resp = await client.get(f"{BASE}/resumes/{resume_id}/file", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == _PDF_BASIC

    async def test_download_other_user_gets_404(self, client: AsyncClient):
        """越权返回 404 而非 403——403 等于承认这个 id 存在"""
        _, headers_a = await _register(client, "da")
        _, headers_b = await _register(client, "db")
        resume_id = (await _upload(client, headers_a)).json()["data"]["id"]
        resp = await client.get(f"{BASE}/resumes/{resume_id}/file", headers=headers_b)
        assert resp.status_code == 404
        assert resp.json()["code"] == 40400

    async def test_download_nonexistent_id(self, client: AsyncClient):
        _, headers = await _register(client, "missing")
        assert (await client.get(f"{BASE}/resumes/999999/file", headers=headers)).status_code == 404

    async def test_download_chinese_filename_rfc5987(self, client: AsyncClient):
        """中文下载名走 RFC 5987 编码（不自己拼响应头，交给 Starlette 处理）"""
        _, headers = await _register(client, "cn")
        resume_id = (await _upload(client, headers, "张三的简历.pdf")).json()["data"]["id"]
        resp = await client.get(f"{BASE}/resumes/{resume_id}/file", headers=headers)
        disposition = resp.headers["content-disposition"]
        assert "filename*=utf-8''" in disposition
        assert "%E5%BC%A0%E4%B8%89" in disposition  # 「张三」的百分号编码
        assert "attachment" in disposition

    async def test_download_history_still_accessible(self, client: AsyncClient):
        """保留多次上传的历史：旧的一份仍然可下载"""
        _, headers = await _register(client, "hist")
        first_id = (await _upload(client, headers, "first.pdf")).json()["data"]["id"]
        await _upload(client, headers, "second.pdf")
        resp = await client.get(f"{BASE}/resumes/{first_id}/file", headers=headers)
        assert resp.status_code == 200

    async def test_download_missing_on_disk_gets_404(self, client: AsyncClient):
        """磁盘文件被删掉时返回 404 而非 500（放在最后：它会清空私有目录）"""
        _, headers = await _register(client, "gone")
        resume_id = (await _upload(client, headers)).json()["data"]["id"]
        for path in Path(settings.RESUME_DIR).glob("*"):
            path.unlink()
        resp = await client.get(f"{BASE}/resumes/{resume_id}/file", headers=headers)
        assert resp.status_code == 404
