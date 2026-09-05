import requests
import json
import time
from config import DEEPSEEK_API_KEY, API_URL, MAX_ROUNDS, MAX_MINUTES, PROMPTS, DEFAULT_POSITION, FALLBACK_QUESTION
from rag_service import RAGService

class AIService:
    def __init__(self):
        self.sessions = {}
        try:
            self.rag = RAGService()
        except Exception as e:
            print(f"⚠️ RAG 初始化失败: {e}，将降级为纯大模型")
            self.rag = None

    # ... 其他方法保持不变 ...

    def generate_question(self, position, round_num, is_follow_up, history):
        """
        根据新的题库策略生成题目：
        - 开场题 (round=1, is_follow_up=False) → 从题库抽取 '开场热身' + 'easy'
        - 追问 (round>=2, is_follow_up=True) → 根据上一题追问触发条件匹配
        - 兜底：返回固定问题
        """
        # 1. 若 RAG 未初始化，直接返回兜底
        if self.rag is None:
            return FALLBACK_QUESTION

        # 2. 开场题
        if not is_follow_up and round_num == 1:
            try:
                row = self.rag.get_opening_question(position)
                if row is not None:
                    return row["面试问题"]
            except Exception as e:
                print(f"⚠️ 获取开场题失败: {e}")
            return FALLBACK_QUESTION

        # 3. 追问
        if is_follow_up and round_num >= 2:
            # 获取上一轮面试官的问题（history中最后一个 interviewer 消息）
            last_interviewer_msg = None
            for msg in reversed(history):
                if msg.get("role") == "interviewer":
                    last_interviewer_msg = msg.get("content", "")
                    break
            if not last_interviewer_msg:
                return FALLBACK_QUESTION

            # 获取上一轮题目在题库中的行数据
            question_row = None
            try:
                question_row = self.rag.get_question_by_text(position, last_interviewer_msg)
            except Exception as e:
                print(f"⚠️ 根据问题文本查找题目失败: {e}")

            # 获取候选人最后一轮回答
            candidate_answer = ""
            for msg in reversed(history):
                if msg.get("role") == "candidate":
                    candidate_answer = msg.get("content", "")
                    break

            # 尝试匹配追问
            try:
                follow_up = self.rag.search_by_trigger(position, candidate_answer, history, question_row=question_row)
                if follow_up:
                    return follow_up
            except Exception as e:
                print(f"⚠️ 追问匹配失败: {e}")

            # 追问匹配失败后
            if follow_up is None:
                # ===== 第一步：判断是否应该进入收尾阶段 =====
                # 轮次 >= 6 或 历史对话超过 5 轮，优先收尾
                if round_num >= 6:
                    try:
                        row = self.rag.get_closing_question(position)
                        if row is not None:
                            print("✅ 进入收尾阶段")
                            return row["面试问题"]
                    except Exception as e:
                        print(f"⚠️ 获取收尾题失败: {e}")
                
                # ===== 第二步：如果还没到收尾轮次，再尝试深度考察 =====
                if round_num >= 3:
                    try:
                        deep_row = self.rag.get_question_by_stage(position, stage="深度考察")
                        if deep_row is not None:
                            print("✅ 进入深度考察阶段")
                            return deep_row["面试问题"]
                    except Exception as e:
                        print(f"⚠️ 获取深度考察题失败: {e}")
                    
                    # 如果深度考察没题，降级为核心考察
                    try:
                        core_row = self.rag.get_question_by_stage(position, stage="核心考察")
                        if core_row is not None:
                            print("✅ 进入核心考察阶段")
                            return core_row["面试问题"]
                    except Exception as e:
                        print(f"⚠️ 获取核心考察题失败: {e}")
                
                # ===== 第三步：实在没题了才返回兜底 =====
                return FALLBACK_QUESTION

            # 如果没有匹配到，尝试使用收尾题（若轮次接近末尾）
            if round_num >= 6:
                try:
                    row = self.rag.get_closing_question(position)
                    if row is not None:
                        return row["面试问题"]
                except Exception as e:
                    print(f"⚠️ 获取收尾题失败: {e}")

            return FALLBACK_QUESTION

        # 其他情况（如非预期的组合）
        return FALLBACK_QUESTION