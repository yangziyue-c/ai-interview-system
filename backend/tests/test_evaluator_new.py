"""评估服务增强版（backend/evaluator_new/）验证：题目素材注入与向后兼容

**为什么用 importlib 按文件路径加载**：`evaluator_new/app.py` 不能通过
`import app` 拿到——`backend/app/` 是主应用包，且 `evaluator_new/` 下也有
同名 `app.py`（3 号原代码注释里记的坑），两者会互相遮蔽。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_EVAL_NEW = _BACKEND / "evaluator_new"


@pytest.fixture(scope="module")
def ev_new():
    """加载 evaluator_new/app.py 模块（只加载一次）"""
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))
    if str(_EVAL_NEW) not in sys.path:
        sys.path.append(str(_EVAL_NEW))  # append：不遮蔽 backend 的 app 包
    spec = importlib.util.spec_from_file_location("eval_new_app", _EVAL_NEW / "app.py")
    if spec is None or spec.loader is None:
        pytest.skip("evaluator_new/app.py 不可加载")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_materials_backward_compatible(ev_new):
    """不传 materials 时输出与 3 号原版逐字一致（向后兼容的硬约束）"""
    qa = [{"round": 1, "question": "Q1", "answer": "A1"}]
    assert ev_new.build_dialogue_text(qa) == "面试官（第1轮）：Q1\n候选人：A1\n"


def test_no_materials_multiple_rounds(ev_new):
    """多轮且无素材时，逐轮格式与旧版一致"""
    qa = [
        {"round": 1, "question": "Q1", "answer": "A1"},
        {"round": 2, "question": "Q2", "answer": "A2"},
    ]
    assert ev_new.build_dialogue_text(qa) == (
        "面试官（第1轮）：Q1\n候选人：A1\n面试官（第2轮）：Q2\n候选人：A2\n"
    )


def test_materials_injected(ev_new):
    """传 materials 时追加「【本题评分参考】」行"""
    qa = [{
        "round": 2, "question": "Q2", "answer": "A2",
        "materials": {
            "basic_score_points": "基础点",
            "advanced_score_points": "进阶层",
            "calibration_anchor": "[技术水平] 标准",
        },
    }]
    out = ev_new.build_dialogue_text(qa)
    assert out.startswith("面试官（第2轮）：Q2\n候选人：A2\n")
    assert "【本题评分参考】" in out
    assert "基础得分点：基础点" in out
    assert "进阶得分点：进阶层" in out
    assert "判分标准：[技术水平] 标准" in out


def test_partial_materials_only_present_fields(ev_new):
    """素材只有部分字段时，只拼有值的项（不留空标签）"""
    qa = [{
        "round": 1, "question": "Q", "answer": "A",
        "materials": {"calibration_anchor": "仅锚点"},
    }]
    out = ev_new.build_dialogue_text(qa)
    assert "判分标准：仅锚点" in out
    assert "基础得分点" not in out
    assert "进阶得分点" not in out


def test_empty_materials_no_extra_line(ev_new):
    """空 materials 字典不产生多余行"""
    qa = [{"round": 1, "question": "Q", "answer": "A", "materials": {}}]
    assert ev_new.build_dialogue_text(qa) == "面试官（第1轮）：Q\n候选人：A\n"


def test_materials_none_no_crash(ev_new):
    """materials 显式为 None 时不崩（主后端未匹配到题目时的形态）"""
    qa = [{"round": 1, "question": "Q", "answer": "A", "materials": None}]
    assert ev_new.build_dialogue_text(qa) == "面试官（第1轮）：Q\n候选人：A\n"


def test_all_positions_have_prompt_materials(ev_new):
    """每个在册岗位都必须有非空的 Prompt 素材

    回归：原实现 `_KEY_POINTS.get(code, "")` 让**在册但无专属文案**的岗位
    （V5 新启用的 algorithm / system_design）拿到空串，Prompt 里出现
    「核心考察点：」后什么都没有 —— 岗位在册却被当成"无配置"。
    """
    from evaluation_prompts import POSITION_CONFIG

    assert set(POSITION_CONFIG) >= {
        "backend", "frontend", "test_engineer", "algorithm", "system_design",
    }
    for code, cfg in POSITION_CONFIG.items():
        assert cfg["key_points"].strip(), f"{code} 的 key_points 为空"
        assert cfg["position_desc"].strip(), f"{code} 的 position_desc 为空"
