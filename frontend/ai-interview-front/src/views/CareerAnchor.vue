<template>
  <div class="anchor-page" :class="{ 'is-desktop': isDesktop }">
    <div class="page-header">
      <button class="back-btn" @click="goBack">
        <AppIcon name="chevron-left" :size="18" />
        <span>返回</span>
      </button>

      <div class="header-center">
        <span class="page-title">岗位倾向速测</span>
        <span class="page-subtitle">{{ questions.length }} 条陈述 · 约 3 分钟</span>
      </div>

      <div class="header-right">
        <span v-if="!finished" class="progress-text">{{ current + 1 }} / {{ questions.length }}</span>
      </div>
    </div>

    <div v-if="!finished" class="quiz-body">
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>

      <div class="question-card">
        <div class="question-meta">
          <span class="question-index">Q{{ current + 1 }}</span>
          <span class="question-type">{{ questionGroupLabel }}</span>
        </div>
        <h2 class="question-title">{{ currentQuestion.title }}</h2>
        <p class="question-guide">{{ questionGuide }}</p>

        <button
          v-for="rating in ratingOptions"
          :key="rating.value"
          class="option-card"
          :class="{ selected: answers[current] === rating.value }"
          @click="selectRating(rating.value)"
        >
          <span class="option-key">{{ rating.value }}</span>
          <span class="option-text">{{ rating.label }}</span>
          <AppIcon
            v-if="answers[current] === rating.value"
            name="check"
            :size="18"
            class="option-check"
          />
        </button>
      </div>

      <div class="quiz-actions">
        <button class="btn btn-secondary" :disabled="current === 0" @click="prev">上一题</button>
        <button
          class="btn btn-primary"
          :disabled="answers[current] === null || submitting"
          @click="next"
        >
          {{ submitting ? '正在生成推荐…' : (isLast ? '查看结果' : '下一题') }}
        </button>
      </div>

      <p class="quiz-note">这是岗位倾向速测，不是正式职业锚测评，结果仅供参考。</p>
    </div>

    <div v-else class="result-body">
      <p v-if="submitError" class="quiz-note">{{ submitError }}</p>
      <div class="result-card">
        <div class="result-badge">
          <AppIcon name="sparkles" :size="18" />
          <span>综合推荐</span>
        </div>

        <h1 class="result-title">{{ recommendationTitle }}</h1>
        <div class="match-summary">
          <span class="match-value">倾向指数 {{ topIndex }} / 100</span>
          <span>置信度 {{ confidenceLabel }}</span>
          <span>回答一致性 {{ consistencyPercent }}%</span>
        </div>
        <p class="result-desc">{{ topNarrative }}</p>

        <div class="score-list">
          <div v-for="item in scoreRows" :key="item.code" class="score-row">
            <div class="score-head">
              <div class="score-label">
                <span class="score-name">{{ item.name }}</span>
                <span class="score-detail">
                  兴趣 {{ item.interestRaw }} / 10 · 能力 {{ item.abilityRaw }} / 10
                </span>
              </div>
              <span class="score-value">{{ item.index }}</span>
            </div>
            <div class="score-track">
              <div
                class="score-fill"
                :class="{ primary: item.code === topCode }"
                :style="{ width: item.index + '%' }"
              ></div>
            </div>
          </div>
        </div>

        <div class="diagnostic-card">
          <div class="secondary-head">
            <div>
              <span class="secondary-label">兴趣与能力信号</span>
              <strong class="secondary-name">{{ signalLabel }}</strong>
            </div>
            <span class="secondary-score">{{ confidenceLabel }}</span>
          </div>
          <p>{{ signalNarrative }}</p>
        </div>

        <div class="secondary-card">
          <div class="secondary-head">
            <div>
              <span class="secondary-label">第二方向</span>
              <strong class="secondary-name">{{ secondName }}</strong>
            </div>
            <span class="secondary-score">{{ secondIndex }}</span>
          </div>
          <p>{{ secondReason }}</p>
        </div>

        <div class="result-actions">
          <button class="btn btn-primary" @click="goInterview(topCode)">
            去 {{ topName }} 面试
          </button>
          <button class="btn btn-secondary" @click="goInterview(secondCode)">
            也看看 {{ secondName }}
          </button>
        </div>
        <button class="restart-btn" @click="restart">重新测一次</button>
        <p class="result-note">
          结果用于比较岗位探索优先级，不代表岗位胜任度，也不替代正式职业测评。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { submitCareerAnswers } from '@/api/career'

const router = useRouter()
const isDesktop = useMediaQuery('(min-width: 1024px)')

const POSITIONS = {
  backend: { code: 'backend', name: 'Java 后端开发' },
  frontend: { code: 'frontend', name: 'Web 前端开发' },
  test_engineer: { code: 'test_engineer', name: '测试开发工程师' },
  system_design: { code: 'system_design', name: '系统设计工程师' },
  algorithm: { code: 'algorithm', name: '算法工程师' }
}

const REASONS = {
  backend: '更关注数据、接口与系统稳定性，Java 后端的学习路径和你的选择更接近。',
  frontend: '更关注交互、体验与工程化，Web 前端的学习路径和你的选择更接近。',
  test_engineer: '更关注质量、边界与可验证性，测试开发的成长路径和你的选择更接近。',
  system_design: '更关注架构、容量与高可用，系统设计方向的综合要求与你的回答更接近。',
  algorithm: '更关注模型效果与指标提升，算法工程方向与你的兴趣和能力自评更接近。'
}

const CODES = ['backend', 'frontend', 'test_engineer', 'algorithm', 'system_design']
const QUESTION_TYPES = {
  interest: '兴趣与偏好',
  ability: '能力与经历'
}

const INTEREST_RATINGS = [
  { value: 1, label: '完全不符合' },
  { value: 2, label: '不太符合' },
  { value: 3, label: '一般或不确定' },
  { value: 4, label: '比较符合' },
  { value: 5, label: '非常符合' }
]

const ABILITY_RATINGS = [
  { value: 1, label: '目前做不到' },
  { value: 2, label: '需要较多帮助' },
  { value: 3, label: '基本了解，但不够独立' },
  { value: 4, label: '基本可以独立完成' },
  { value: 5, label: '能够稳定独立完成' }
]

// 题目与后端 app/core/career_anchor.py 的 SCALE_QUESTIONS 同源；
// 改题时两边必须同步，否则提交的 20 条评分与题目顺序会对不上。
const questions = [
  {
    category: 'interest',
    role: 'backend',
    title: '我喜欢把业务规则拆成清晰的数据模型和接口边界。'
  },
  {
    category: 'interest',
    role: 'frontend',
    title: '我愿意反复打磨页面交互、视觉细节和操作路径。'
  },
  {
    category: 'interest',
    role: 'test_engineer',
    title: '我喜欢提前设计异常场景和验收标准。'
  },
  {
    category: 'interest',
    role: 'system_design',
    title: '我喜欢权衡模块边界、容量、扩展性和可用性。'
  },
  {
    category: 'interest',
    role: 'algorithm',
    title: '我愿意用数据和实验判断一个方案是否真的有效。'
  },
  {
    category: 'interest',
    role: 'backend',
    title: '看到一套服务稳定支撑高并发请求，我会很有成就感。'
  },
  {
    category: 'interest',
    role: 'frontend',
    title: '我享受把复杂功能整理成清晰、顺手的界面。'
  },
  {
    category: 'interest',
    role: 'test_engineer',
    title: '我愿意追查偶现问题，直到它能够稳定复现。'
  },
  {
    category: 'interest',
    role: 'system_design',
    title: '我对多个服务如何协作、部署和承受流量很感兴趣。'
  },
  {
    category: 'interest',
    role: 'algorithm',
    title: '我喜欢研究模型、特征或指标为什么发生变化。'
  },
  {
    category: 'ability',
    role: 'backend',
    title: '我能独立设计数据表、接口和基本的登录权限。'
  },
  {
    category: 'ability',
    role: 'frontend',
    title: '我能独立完成响应式页面、组件交互和状态联动。'
  },
  {
    category: 'ability',
    role: 'test_engineer',
    title: '我能独立设计测试用例、自动化脚本和回归检查。'
  },
  {
    category: 'ability',
    role: 'system_design',
    title: '我能拆分模块、画架构图并说明部署方案。'
  },
  {
    category: 'ability',
    role: 'algorithm',
    title: '我能完成数据清洗、模型训练和基本效果评估。'
  },
  {
    category: 'ability',
    role: 'backend',
    title: '遇到数据库异常、并发或消息堆积时，我知道从哪里排查。'
  },
  {
    category: 'ability',
    role: 'frontend',
    title: '遇到渲染、兼容性或网络请求问题时，我能定位到具体环节。'
  },
  {
    category: 'ability',
    role: 'test_engineer',
    title: '我能复现环境差异、边界输入和偶现缺陷。'
  },
  {
    category: 'ability',
    role: 'system_design',
    title: '我能分析服务依赖、资源瓶颈和扩展方案。'
  },
  {
    category: 'ability',
    role: 'algorithm',
    title: '遇到指标异常时，我能判断是数据、特征还是训练过程的问题。'
  }
]

const current = ref(0)
const answers = ref(Array(questions.length).fill(null))
const finished = ref(false)
const remoteResult = ref(null)
const submitting = ref(false)
const submitError = ref('')

const currentQuestion = computed(() => questions[current.value])
const isLast = computed(() => current.value === questions.length - 1)
const progressPercent = computed(() => Math.round(((current.value + 1) / questions.length) * 100))
const questionGroupLabel = computed(() => QUESTION_TYPES[currentQuestion.value.category])
const ratingOptions = computed(() => (
  currentQuestion.value.category === 'interest' ? INTEREST_RATINGS : ABILITY_RATINGS
))
const questionGuide = computed(() => (
  currentQuestion.value.category === 'interest'
    ? '请根据真实偏好选择，不必考虑当前能力。'
    : '请根据目前能否独立完成选择，不必考虑是否喜欢。'
))

const categoryScores = computed(() => {
  const result = {
    interest: Object.fromEntries(CODES.map((code) => [code, 0])),
    ability: Object.fromEntries(CODES.map((code) => [code, 0]))
  }
  answers.value.forEach((idx, qIdx) => {
    if (idx === null) return
    const question = questions[qIdx]
    result[question.category][question.role] += idx
  })
  return result
})

const preferenceRanked = computed(() => {
  return CODES.map((code) => ({
    code,
    value: (categoryScores.value.interest[code] - 6) / 4
  })).sort((a, b) => {
    if (b.value !== a.value) return b.value - a.value
    return CODES.indexOf(a.code) - CODES.indexOf(b.code)
  })
})

const abilityRanked = computed(() => {
  return CODES.map((code) => ({
    code,
    value: (categoryScores.value.ability[code] - 6) / 4
  })).sort((a, b) => {
    if (b.value !== a.value) return b.value - a.value
    return CODES.indexOf(a.code) - CODES.indexOf(b.code)
  })
})

const ranked = computed(() => {
  return CODES.map((code) => {
    const interestNorm = (categoryScores.value.interest[code] - 6) / 4
    const abilityNorm = (categoryScores.value.ability[code] - 6) / 4
    const composite = interestNorm * 0.6 + abilityNorm * 0.4
    return {
      code,
      name: POSITIONS[code].name,
      interestRaw: categoryScores.value.interest[code],
      abilityRaw: categoryScores.value.ability[code],
      interestNorm,
      abilityNorm,
      composite,
      index: Math.round((composite + 1) * 50)
    }
  }).sort((a, b) => {
    if (b.composite !== a.composite) return b.composite - a.composite
    if (b.abilityNorm !== a.abilityNorm) return b.abilityNorm - a.abilityNorm
    if (b.interestNorm !== a.interestNorm) return b.interestNorm - a.interestNorm
    return CODES.indexOf(a.code) - CODES.indexOf(b.code)
  })
})

const topCode = computed(() => remoteResult.value?.recommended?.position || ranked.value[0].code)
const topName = computed(() => remoteResult.value?.recommended?.name || POSITIONS[topCode.value].name)
const topIndex = computed(() => remoteResult.value?.recommended?.index ?? ranked.value[0].index)
const secondCode = computed(() => remoteResult.value?.alternatives?.[0]?.position || ranked.value[1].code)
const secondName = computed(() => remoteResult.value?.alternatives?.[0]?.name || ranked.value[1].name)
const secondIndex = computed(() => remoteResult.value?.alternatives?.[0]?.index ?? ranked.value[1].index)
const secondReason = computed(() => REASONS[secondCode.value] || '')
const topInterestCode = computed(() => preferenceRanked.value[0].code)
const topAbilityCode = computed(() => abilityRanked.value[0].code)

const consistencyPercent = computed(() => {
  if (remoteResult.value?.consistency_percent !== undefined) {
    return remoteResult.value.consistency_percent
  }
  let totalDifference = 0
  let pairCount = 0
  CODES.forEach((code) => {
    ;['interest', 'ability'].forEach((category) => {
      const values = questions
        .map((question, index) => ({ question, value: answers.value[index] }))
        .filter((item) => item.question.category === category && item.question.role === code)
        .map((item) => item.value)
        .filter((value) => value !== null)
      if (values.length === 2) {
        totalDifference += Math.abs(values[0] - values[1])
        pairCount += 1
      }
    })
  })
  if (pairCount === 0) return 0
  return Math.round((1 - totalDifference / (pairCount * 4)) * 100)
})

const scoreMargin = computed(() => topIndex.value - secondIndex.value)
const recommendationTitle = computed(() => (
  remoteResult.value?.title || (scoreMargin.value < 5 ? '方向暂不明确' : topName.value)
))
const confidenceLabel = computed(() => {
  if (remoteResult.value?.confidence) return remoteResult.value.confidence
  if (consistencyPercent.value >= 75 && scoreMargin.value >= 10) return '高'
  if (consistencyPercent.value >= 50 && scoreMargin.value >= 5) return '中'
  return '低'
})

const topNarrative = computed(() => {
  if (remoteResult.value?.narrative) return remoteResult.value.narrative
  const interestName = POSITIONS[topInterestCode.value].name
  const abilityName = POSITIONS[topAbilityCode.value].name
  if (scoreMargin.value < 5) {
    return `当前相对最高的是「${topName.value}」，但与「${secondName.value}」的分差只有 ${scoreMargin.value} 分，暂时不能形成明确的主推荐。建议补充项目经历后再测，或先分别体验这两个方向。`
  }
  if (topInterestCode.value === topAbilityCode.value) {
    return `兴趣量表与能力自评都更支持「${interestName}」。${REASONS[topCode.value]}`
  }
  return `兴趣量表更偏向「${interestName}」，能力自评更偏向「${abilityName}」。按兴趣 60%、能力 40% 综合后，当前优先推荐「${topName}」。`
})

const signalLabel = computed(() => {
  if (remoteResult.value?.signal_label) return remoteResult.value.signal_label
  if (scoreMargin.value < 5) return '各方向区分度不足'
  return topInterestCode.value === topAbilityCode.value ? '兴趣与能力方向一致' : '兴趣与能力方向存在差异'
})

const signalNarrative = computed(() => {
  if (remoteResult.value?.signal_narrative) return remoteResult.value.signal_narrative
  const interestName = POSITIONS[topInterestCode.value].name
  const abilityName = POSITIONS[topAbilityCode.value].name
  if (scoreMargin.value < 5) {
    return '各岗位的倾向指数过于接近，当前无法可靠判断兴趣与能力的优势方向。建议补充真实项目经历后重测，或分别体验排名靠前的岗位。'
  }
  let narrative
  if (topInterestCode.value === topAbilityCode.value) {
    narrative = `两类量表都把「${interestName}」排在首位，方向较一致。`
  } else {
    narrative = `兴趣最高的是「${interestName}」，能力自评最高的是「${abilityName}」。建议先用项目或模拟面试验证兴趣方向，同时评估能力方向的提升空间。`
  }
  if (confidenceLabel.value === '低') {
    return `${narrative} 当前主次分差较小，或同类陈述的回答不够稳定，结果只适合作为初步线索。`
  }
  if (confidenceLabel.value === '中') {
    return `${narrative} 结果具有一定区分度，但仍建议结合一次真实练习验证。`
  }
  return `${narrative} 主次方向区分较清楚，可以作为优先探索方向。`
})

const scoreRows = computed(() => {
  if (remoteResult.value?.scores) {
    return remoteResult.value.scores.map((item) => ({
      code: item.position,
      name: item.name,
      interestRaw: item.interest_raw,
      abilityRaw: item.ability_raw,
      index: item.index
    }))
  }
  return ranked.value
})

const selectRating = (rating) => {
  answers.value[current.value] = rating
}

const next = async () => {
  if (answers.value[current.value] === null) return
  if (!isLast.value) {
    current.value += 1
    scrollToTop()
    return
  }

  submitting.value = true
  submitError.value = ''
  try {
    remoteResult.value = await submitCareerAnswers(answers.value)
  } catch (e) {
    // 后端暂时不可用时回退本地计算，保证演示与离线场景仍能出结果
    remoteResult.value = null
    submitError.value = '推荐服务暂时不可用，当前结果由本地计算生成。'
  } finally {
    submitting.value = false
  }

  finished.value = true
  try {
    localStorage.setItem('career_anchor_result', JSON.stringify({
      version: 4,
      code: topCode.value,
      secondCode: secondCode.value,
      scores: Object.fromEntries(scoreRows.value.map((item) => [item.code, {
        interestRaw: item.interestRaw,
        abilityRaw: item.abilityRaw,
        index: item.index
      }])),
      consistencyPercent: consistencyPercent.value,
      confidence: confidenceLabel.value,
      at: Date.now()
    }))
  } catch (e) {
    // localStorage 不可用时不影响结果展示
  }
  scrollToTop()
}

const prev = () => {
  if (current.value > 0) {
    current.value -= 1
    scrollToTop()
  }
}

const restart = () => {
  answers.value = Array(questions.length).fill(null)
  current.value = 0
  finished.value = false
  remoteResult.value = null
  submitError.value = ''
  scrollToTop()
}

const scrollToTop = () => {
  nextTick(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
}

const goBack = () => {
  router.push('/main/interview')
}

const goInterview = (code) => {
  router.push({
    path: '/main/interview/detail',
    query: { code }
  })
}
</script>

<style scoped>
.anchor-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 var(--space-4) var(--space-8);
  font-family: var(--font-sans);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) 0 var(--space-4);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2) var(--space-1) var(--space-1);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
}

.back-btn:hover {
  color: var(--text-primary);
  background: var(--gray-100);
}

.header-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 0;
}

.page-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.page-subtitle {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.header-right {
  flex-shrink: 0;
  min-width: 52px;
  text-align: right;
}

.progress-text {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.quiz-body,
.result-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.progress-track {
  height: 6px;
  overflow: hidden;
  background: var(--gray-100);
  border-radius: var(--radius-full);
}

.progress-fill {
  height: 100%;
  background: var(--text-primary);
  border-radius: var(--radius-full);
  transition: width 0.25s var(--ease-out, ease);
}

.question-card,
.result-card {
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.question-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.question-index {
  display: inline-block;
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-tertiary);
  letter-spacing: 0.04em;
}

.question-type {
  padding: 2px var(--space-2);
  background: var(--gray-100);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.question-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-lg);
  line-height: 1.5;
  color: var(--text-primary);
}

.question-guide {
  margin: 0 0 var(--space-4);
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-tertiary);
}

.option-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  margin-bottom: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--gray-50);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-size: var(--text-sm);
  line-height: 1.6;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.option-card:hover {
  border-color: var(--gray-500);
}

.option-card.selected {
  background: var(--bg-card);
  border-color: var(--text-primary);
}

.option-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  background: var(--gray-100);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
}

.option-card.selected .option-key {
  background: var(--text-primary);
  color: var(--bg-card);
}

.option-text {
  flex: 1;
  min-width: 0;
}

.option-check {
  flex-shrink: 0;
  color: var(--text-primary);
}

.quiz-actions {
  display: flex;
  gap: var(--space-3);
}

.quiz-actions .btn {
  flex: 1;
}

.quiz-note {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-tertiary);
  text-align: center;
}

.result-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.result-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  align-self: flex-start;
  padding: 3px var(--space-3);
  background: var(--gray-100);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.result-title {
  margin: 0;
  font-size: 28px;
  line-height: 1.25;
  color: var(--text-primary);
}

.result-desc {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--text-secondary);
}

.match-summary {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.match-value {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.score-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-subtle);
}

.score-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
  font-size: var(--text-sm);
}

.score-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.score-name {
  color: var(--text-primary);
}

.score-detail {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.score-value {
  flex-shrink: 0;
  color: var(--text-tertiary);
}

.score-track {
  height: 8px;
  overflow: hidden;
  background: var(--gray-100);
  border-radius: var(--radius-full);
}

.score-fill {
  height: 100%;
  background: var(--gray-500);
  border-radius: var(--radius-full);
  transition: width 0.3s var(--ease-out, ease);
}

.score-fill.primary {
  background: var(--text-primary);
}

.secondary-card,
.diagnostic-card {
  padding: var(--space-3);
  background: var(--gray-50);
  border-radius: var(--radius-md);
}

.secondary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.secondary-label {
  display: block;
  margin-bottom: 2px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.secondary-name {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.secondary-score {
  flex-shrink: 0;
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.secondary-card p,
.diagnostic-card p {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--text-secondary);
}

.result-actions {
  display: flex;
  gap: var(--space-3);
}

.result-actions .btn {
  flex: 1;
}

.restart-btn {
  align-self: center;
  padding: var(--space-1) var(--space-2);
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  cursor: pointer;
}

.restart-btn:hover {
  color: var(--text-primary);
}

.result-note {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-tertiary);
  text-align: center;
}

@media (max-width: 480px) {
  .anchor-page {
    padding: 0 var(--space-3) var(--space-6);
  }

  .question-card,
  .result-card {
    padding: var(--space-4);
  }

  .result-title {
    font-size: 24px;
  }

  .result-actions {
    flex-direction: column;
  }

  .match-summary {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--space-1);
  }
}
</style>
