import pandas as pd
import re
from pathlib import Path
import random

class RAGService:
    FILE_MAP = {
        "backend": "Java后端面试题库_150题_个性化内容_v13.xlsx",
        "frontend": "Web前端面试题库_150题_个性化内容_v13.xlsx",
        "test_engineer": "软件测试开发面试题库_150题_个性化内容_v13.xlsx"
    }
    POSITION_NAME_MAP = {
        "backend": "Java后端",
        "frontend": "Web前端",
        "test_engineer": "软件测试开发"
    }

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent
        self._dfs = {}

    def _load_df(self, position):
        if position in self._dfs:
            return self._dfs[position]
        filename = self.FILE_MAP.get(position)
        if not filename:
            raise ValueError(f"未知岗位: {position}")
        filepath = self.base_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"题库文件不存在: {filepath}")
        df = pd.read_excel(filepath, sheet_name="面试题库")
        self._dfs[position] = df
        return df

    def get_opening_question(self, position):
        """获取开场题：interview_stage='开场热身' 且 difficulty='easy'"""
        df = self._load_df(position)
        pos_name = self.POSITION_NAME_MAP.get(position)
        filtered = df[df["所属岗位"] == pos_name]
        filtered = filtered[(filtered["面试阶段"] == "开场热身") & (filtered["难度等级"] == "easy")]
        if filtered.empty:
            return None
        row = filtered.sample(1).iloc[0]
        return row

    def get_closing_question(self, position):
        """获取收尾题：interview_stage='收尾交流'"""
        df = self._load_df(position)
        pos_name = self.POSITION_NAME_MAP.get(position)
        filtered = df[df["所属岗位"] == pos_name]
        filtered = filtered[filtered["面试阶段"] == "收尾交流"]
        if filtered.empty:
            return None
        row = filtered.sample(1).iloc[0]
        return row

    def get_question_by_text(self, position, question_text):
        """根据问题文本精确匹配题目行"""
        df = self._load_df(position)
        pos_name = self.POSITION_NAME_MAP.get(position)
        # 去除首尾空格，精确匹配
        matched = df[(df["所属岗位"] == pos_name) & (df["面试问题"].str.strip() == question_text.strip())]
        if matched.empty:
            # 尝试包含匹配（用于模糊场景）
            matched = df[(df["所属岗位"] == pos_name) & (df["面试问题"].str.contains(question_text.strip(), na=False))]
        if matched.empty:
            return None
        return matched.iloc[0]

    def search_by_trigger(self, position, candidate_answer, history, question_row=None):
        """
        根据候选人的回答和上一题的行数据，匹配追问触发条件。
        如果未传入question_row，则降级为全库搜索（兼容旧逻辑，但建议传入）。
        """
        if question_row is None:
            # 兼容旧调用，但建议修改调用方
            return self._legacy_search_by_trigger(position, candidate_answer, history)

        trigger_text = question_row.get("追问触发条件", "")
        if pd.isna(trigger_text) or not trigger_text:
            return None

        # 解析追问触发条件
        parsed = self._parse_follow_up_triggers(trigger_text)
        l1_matches = parsed.get("l1", [])        # [(keyword, follow_up), ...]
        fallback_list = parsed.get("fallback", [])  # [question_text, ...]

        # 收集已问过的追问（避免重复）
        asked = set()
        for msg in history:
            if msg.get("role") == "interviewer":
                asked.add(msg.get("content", "").strip())

        # 1. 尝试匹配 L1 关键词
        for keyword, follow_up in l1_matches:
            if keyword and keyword.lower() in candidate_answer.lower():
                if follow_up and follow_up not in asked:
                    return follow_up

        # 2. 如果回答笼统（短回答或包含不确定词），使用降级策略
        if self._is_vague_answer(candidate_answer):
            for fb in fallback_list:
                if fb and fb not in asked:
                    return fb

        # 3. 都没有匹配，返回 None（调用方会降级）
        return None

    def _legacy_search_by_trigger(self, position, candidate_answer, history):
        """兼容旧调用，全库搜索（已弃用）"""
        # 保留原有逻辑或返回 None
        return None

    def _parse_follow_up_triggers(self, text):
        """
        解析追问触发条件文本，返回结构化数据。
        返回格式: {
            'l1': [(keyword, follow_up), ...],
            'l2': [...],
            'l3': [...],
            'fallback': [...]
        }
        """
        result = {"l1": [], "l2": [], "l3": [], "fallback": []}
        if not isinstance(text, str):
            return result

        lines = text.split('\n')
        current_section = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if "【L1" in line or "L1-触发追问" in line:
                current_section = "l1"
                continue
            elif "【L2" in line or "L2-深入追问" in line:
                current_section = "l2"
                continue
            elif "【L3" in line or "L3-极限追问" in line:
                current_section = "l3"
                continue
            elif "降级策略" in line:
                current_section = "fallback"
                continue

            if current_section == "l1":
                # 匹配 "若提到"X" → 追问：Y"
                match = re.search(r'若提到["“](.+?)["”]\s*[→-]\s*追问[:：]\s*(.+)', line)
                if match:
                    keyword = match.group(1).strip()
                    follow_up = match.group(2).strip()
                    result["l1"].append((keyword, follow_up))
            elif current_section == "fallback":
                # 匹配 "→ 那我们先从..." 等
                if "→" in line:
                    fb = line.split("→", 1)[1].strip()
                    if fb:
                        result["fallback"].append(fb)
            # l2/l3 暂不处理，可扩展

        return result

    def _is_vague_answer(self, text):
        """判断回答是否笼统（短、缺乏细节）"""
        if not text:
            return True
        # 长度小于20个字符或包含常见的模糊词
        if len(text) < 20:
            return True
        vague_words = ["不知道", "不清楚", "不太懂", "简单", "基本", "大概"]
        for w in vague_words:
            if w in text:
                return True
        return False
    def get_question_by_stage(self, position, stage="深度考察", difficulty=None):
        """根据面试阶段抽取题目，可指定难度"""
        df = self._load_df(position)
        pos_name = self.POSITION_NAME_MAP.get(position)
        filtered = df[df["所属岗位"] == pos_name]
        filtered = filtered[filtered["面试阶段"] == stage]
        if difficulty:
            filtered = filtered[filtered["难度等级"] == difficulty]
        if filtered.empty:
            return None
        row = filtered.sample(1).iloc[0]
        return row