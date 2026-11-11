"""简历字段抽取与文件工具的纯函数测试

不依赖 pypdf、也不需要数据库，跑得飞快。

**反例是主体**：抽错字段会把用户已经填对的信息引导成错的（预填了用户就懒得改），
比抽不出来危害大得多——所以每条规则都要钉死「不许猜」的边界。
"""
import pytest

from app.core.resume_fields import decide_status, extract_fields, looks_garbled, normalize
from app.core.resume_files import (
    ALLOWED_RESUME_EXT,
    RESUME_MEDIA_TYPES,
    new_stored_name,
    resume_file_path,
    sanitize_filename,
)


def _values(text: str) -> tuple:
    g = extract_fields(text)
    return g.nickname.value, g.student_id.value, g.target_position.value


class TestStudentId:
    def test_label_hit(self):
        """标签命中：中文标签、带空格、英文标签"""
        assert extract_fields("学号：20210001").student_id.value == "20210001"
        assert extract_fields("学  号：2021ABC01").student_id.value == "2021ABC01"
        assert extract_fields("Student ID: 20210001").student_id.value == "20210001"

    def test_rejects_phone_year_and_id_card(self):
        """手机号、年份、身份证号都不算学号"""
        assert extract_fields("学号：13800138000").student_id.value is None
        assert extract_fields("学号：2021").student_id.value is None
        assert extract_fields("学号：110101199003074567").student_id.value is None

    def test_unparsable_label_value(self):
        """标签值不采用的两条分支：压根不是编号 / 形似编号但不像学号"""
        assert extract_fields("学号：无").student_id.value is None
        g = extract_fields("学号：13800138000")
        assert g.student_id.value is None
        assert "不像学号" in g.student_id.note  # 明确说明为何不采用

    def test_weak_rule_standalone_line(self):
        """弱规则：文档前部独立成行的编号"""
        g = extract_fields("张三\n20210001\n后端开发")
        assert g.student_id.value == "20210001"
        assert "请核对" in g.student_id.note  # 弱规则必须标注是推测

    def test_none_when_nothing_found(self):
        assert extract_fields("这是一份没有编号的简历").student_id.value is None


class TestNickname:
    def test_label_hit(self):
        assert extract_fields("姓名：张三").nickname.value == "张三"
        assert extract_fields("姓名：欧阳娜娜").nickname.value == "欧阳娜娜"
        assert extract_fields("姓名：阿依古丽·买买提").nickname.value == "阿依古丽·买买提"
        assert extract_fields("Name: Zhang San").nickname.value == "Zhang San"

    def test_label_boundary_rejects_sentence(self):
        """边界断言：姓名后紧跟描述时整条不命中（否则会切出「张三是本」这种假名字）"""
        assert extract_fields("姓名：张三是本次候选人").nickname.value is None
        assert extract_fields("姓名：无").nickname.value is None

    def test_first_line_fallback(self):
        """首行兜底：孤立一行的姓名能抽到，且标注为推测"""
        g = extract_fields("张三\n求职意向：后端开发")
        assert g.nickname.value == "张三"
        assert "请核对" in g.nickname.note

    def test_first_line_blacklist(self):
        """标题、校名、栏目名都不当姓名"""
        assert extract_fields("个人简历\n教育背景\n北京大学").nickname.value is None
        assert extract_fields("北京大学\n软件工程").nickname.value is None
        assert extract_fields("教育背景\n2021.09-2025.06").nickname.value is None

    def test_heading_then_name(self):
        """首行是标题时，第二行的姓名仍能抽到"""
        assert extract_fields("个人简历\n张三\n电话：13800138000").nickname.value == "张三"


class TestTargetPosition:
    @pytest.mark.parametrize(
        "fragment,expected",
        [
            ("Java 后端开发工程师", "backend"),
            ("Vue3 前端开发", "frontend"),
            ("自动化测试工程师", "test_engineer"),
            ("算法工程师（机器学习方向）", "algorithm"),
            ("系统架构师", "system_design"),
        ],
    )
    def test_all_five_codes_from_label(self, fragment, expected):
        """求职意向标签下五个岗位都能认出"""
        assert extract_fields(f"求职意向：{fragment}").target_position.value == expected

    def test_english_labels_and_position_names(self):
        """英文简历：英文标签 + 英文岗位名同样能识别（PDF 夹具只能放 ASCII，走的就是这条）"""
        g = extract_fields(
            "Name: Zhang San\nStudent ID: 20210001\nTarget Position: Backend Engineer"
        )
        assert g.nickname.value == "Zhang San"
        assert g.student_id.value == "20210001"
        assert g.target_position.value == "backend"

    def test_ambiguous_returns_none(self):
        """两个方向并列时不猜"""
        assert extract_fields("求职意向：前端 / 后端").target_position.value is None

    def test_language_words_score_zero(self):
        """通用编程语言不给分：算法岗简历常写 Java，不能因此判成后端"""
        text = "求职意向：算法工程师\n熟悉 Java、Python、C++、PyTorch、深度学习"
        assert extract_fields(text).target_position.value == "algorithm"
        # 光有语言词、没有任何方向词 → 不猜
        assert extract_fields("熟悉 Java、Python、C++、Go").target_position.value is None

    def test_only_weak_keywords_returns_none(self):
        """只有跨岗位的技术栈弱词时够不着阈值"""
        assert extract_fields("熟悉 MySQL、Redis、Docker 的使用").target_position.value is None

    def test_fulltext_fallback_marks_as_guess(self):
        """无标签时走全文计分，并标注是推测"""
        g = extract_fields("熟练掌握 Vue 与 React，做过多个前端项目")
        assert g.target_position.value == "frontend"
        assert "推测" in g.target_position.note


class TestGarbledAndStatus:
    def test_normalize_fullwidth(self):
        """全角数字/字母/冒号归一为半角"""
        assert normalize("姓名：２０２１") == "姓名:2021"
        assert normalize("ａｂｃ") == "abc"

    def test_looks_garbled(self):
        assert looks_garbled("(cid:12)(cid:34)(cid:56)")
        assert looks_garbled(chr(0xFFFD) * 20)
        assert looks_garbled(chr(0xE000) * 20)
        # 正常中英混排不能误报——「没有中文就判乱码」是错的，英文简历是合法的
        assert not looks_garbled("张三 Zhang San, Backend Engineer")
        assert not looks_garbled("")
        assert not looks_garbled("   ")

    def test_decide_status(self):
        assert decide_status("") == "no_text_layer"
        assert decide_status("   \n  ") == "no_text_layer"
        assert decide_status("(cid:1)(cid:2)(cid:3)") == "garbled"
        assert decide_status("张三的简历") == "parsed"
        assert decide_status("Zhang San") == "parsed"


class TestResumeFiles:
    def test_sanitize_strips_path_components(self):
        """原始文件名里的路径成分必须剥掉（它会进响应头与前端 DOM）"""
        assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
        assert sanitize_filename("..\\..\\windows\\x.pdf") == "x.pdf"
        assert sanitize_filename("C:/Users/a/简历.pdf") == "简历.pdf"

    def test_sanitize_keeps_chinese_and_handles_empty(self):
        assert sanitize_filename("张三的简历.pdf") == "张三的简历.pdf"
        assert sanitize_filename(None) == "resume"
        assert sanitize_filename("") == "resume"
        assert len(sanitize_filename("x" * 500 + ".pdf")) <= 100

    def test_stored_name_shape(self):
        name = new_stored_name(7, ".pdf")
        assert name.startswith("7_") and name.endswith(".pdf")
        assert len(name) == len("7_") + 12 + len(".pdf")

    def test_resume_file_path_rejects_traversal(self):
        """库里存的文件名带路径成分时直接拒绝（第二道防线）"""
        for bad in ("../x.pdf", "a/b.pdf", "..\\x.pdf", ""):
            with pytest.raises(ValueError):
                resume_file_path(bad)

    def test_media_type_table_covers_whitelist(self):
        """白名单与 Content-Type 表必须一一对应，否则下载会拿到 None 类型"""
        assert ALLOWED_RESUME_EXT == frozenset(RESUME_MEDIA_TYPES)
        assert RESUME_MEDIA_TYPES[".pdf"] == "application/pdf"
