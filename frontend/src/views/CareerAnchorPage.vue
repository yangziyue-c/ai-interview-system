<template>
  <div class="career-container" :class="{ 'is-desktop': isDesktop }">
    <div class="page-header">
      <button class="back-btn" @click="goBack">
        <AppIcon name="chevron-left" :size="18" />
        <span>返回</span>
      </button>
      <h1 class="page-title">职业速测</h1>
      <div class="header-spacer"></div>
    </div>

    <div v-if="loading" class="state-card">
      <AppIcon name="loading" :size="28" class="spin" />
      <p>正在加载题目...</p>
    </div>

    <div v-else-if="result" class="result-section animate-up">
      <div class="result-card recommended-card">
        <div class="result-icon-wrap">
          <AppIcon :name="getJobIconName((result.recommended.position || '').trim())" :size="32" />
        </div>
        <h2 class="result-title">{{ result.title || '推荐岗位' }}</h2>
        <h3 class="result-position">{{ result.recommended.name }}</h3>
        
        <div class="index-badge">
          倾向指数 <strong>{{ result.recommended.index }}</strong> / 100
        </div>

        <p class="result-reason">{{ result.narrative }}</p>
        
        <div class="metrics-row">
          <div class="metric-item">
            <span class="m-val">{{ result.consistency_percent }}%</span>
            <span class="m-label">一致性</span>
          </div>
          <div class="metric-item">
            <span class="m-val">{{ result.confidence }}</span>
            <span class="m-label">置信度</span>
          </div>
          <div class="metric-item">
            <span class="m-val">+{{ result.margin }}</span>
            <span class="m-label">领先分差</span>
          </div>
        </div>

        <button class="start-btn" @click="startInterview(result.recommended.position)">
          <span>开始模拟面试</span>
          <AppIcon name="chevron-right" :size="18" />
        </button>
      </div>

      <div class="signal-card">
        <div class="signal-header">
          <AppIcon name="info" :size="16" />
          <span>{{ result.signal_label }}</span>
        </div>
        <p class="signal-text">{{ result.signal_narrative }}</p>
      </div>

      <div class="alt-section">
        <h4 class="alt-title">其他岗位指数</h4>
        <div class="alt-list">
          <div 
            v-for="score in result.scores.filter(s => s.position !== result.recommended.position)" 
            :key="score.position" 
            class="alt-item"
          >
            <span class="alt-name">{{ score.name }}</span>
            <div class="alt-bar-wrap">
              <div class="alt-bar" :style="{ width: score.index + '%' }"></div>
            </div>
            <span class="alt-score">{{ score.index }}</span>
          </div>
        </div>
      </div>

      <p class="guide-text">{{ result.guide }}</p>
      
      <button class="retake-btn" @click="resetTest">
        <AppIcon name="retry" :size="14" />
        <span>重新测试</span>
      </button>
    </div>

    <div v-else class="test-section">
      <div class="intro-text">
        <p>回答以下 20 个陈述，系统将综合评估你的职业倾向。</p>
        <p class="intro-hint">1 = 完全不符合，5 = 非常符合</p>
      </div>

      <div class="question-group">
        <h3 class="group-title">Part 1: 兴趣倾向</h3>
        <div class="question-list">
          <div v-for="(q, index) in interestQuestions" :key="q.id" class="question-card">
            <div class="q-header">
              <span class="q-index">{{ index + 1 }}</span>
              <h4 class="q-text">{{ q.text }}</h4>
            </div>
            <div class="options-list">
              <div 
                v-for="opt in ratings.interest" 
                :key="opt.value" 
                class="option-item"
                :class="{ selected: answers[q.id] === opt.value }"
                @click="answers[q.id] = opt.value"
              >
                <div class="radio-circle">
                  <div class="radio-dot"></div>
                </div>
                <span class="opt-val">{{ opt.value }}</span>
                <span class="opt-label">{{ opt.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="question-group">
        <h3 class="group-title">Part 2: 能力自评</h3>
        <div class="question-list">
          <div v-for="(q, index) in abilityQuestions" :key="q.id" class="question-card">
            <div class="q-header">
              <span class="q-index">{{ index + 11 }}</span>
              <h4 class="q-text">{{ q.text }}</h4>
            </div>
            <div class="options-list">
              <div 
                v-for="opt in ratings.ability" 
                :key="opt.value" 
                class="option-item"
                :class="{ selected: answers[q.id] === opt.value }"
                @click="answers[q.id] = opt.value"
              >
                <div class="radio-circle">
                  <div class="radio-dot"></div>
                </div>
                <span class="opt-val">{{ opt.value }}</span>
                <span class="opt-label">{{ opt.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="submit-bar">
        <button 
          class="submit-btn" 
          :disabled="!isFormComplete || submitting"
          @click="handleSubmit"
        >
          {{ submitting ? '正在生成报告...' : '提交并查看结果' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getJobIconName } from '@/config/jobIcons'
import { getCareerAnchorQuestions, submitCareerAnchor } from '@/api/careerAnchor'
import { updateMe } from '@/api/auth'
import { getSettings, updateSettings } from '@/api/settings'
import { getPositionName } from '@/api/position'
import { confirmDialog } from '@/utils/confirm'
import { showToast } from '@/utils/toast'

const router = useRouter()
const route = useRoute()
const isDesktop = useMediaQuery('(min-width: 1024px)')

const loading = ref(true)
const submitting = ref(false)
const result = ref(null)

const questions = ref([])
const ratings = ref({ interest: [], ability: [] })
const answers = reactive({})

const interestQuestions = computed(() => questions.value.filter(q => q.category === 'interest'))
const abilityQuestions = computed(() => questions.value.filter(q => q.category === 'ability'))

const isFormComplete = computed(() => {
  if (questions.value.length === 0) return false
  return questions.value.every(q => !!answers[q.id])
})

const loadQuestions = async () => {
  loading.value = true
  try {
    const data = await getCareerAnchorQuestions()
    questions.value = data.questions || []
    ratings.value.interest = data.interest_ratings || []
    ratings.value.ability = data.ability_ratings || []
    
    questions.value.forEach(q => {
      answers[q.id] = null
    })
  } catch (e) {
    console.error('加载题目失败', e)
    showToast('加载题目失败，请重试')
  } finally {
    loading.value = false
  }
}

const handleSubmit = async () => {
  if (!isFormComplete.value || submitting.value) return
  submitting.value = true
  try {
    const answerArray = questions.value.map(q => answers[q.id])
    const data = await submitCareerAnchor(answerArray)
    result.value = data

    if (data.recommended?.position) {
      const recPos = data.recommended.position
      const recName = data.recommended.name
      
      const currentSettings = await getSettings().catch(() => null)
      const currentDefault = currentSettings?.default_position

      if (!currentDefault) {
        await updateMe({ target_position: recPos }).catch(e => console.warn(e))
        await updateSettings({ default_position: recPos }).catch(e => console.warn(e))
        showToast(`「${recName}」已设置为默认岗位`)
      } else if (currentDefault !== recPos) {
        const currentName = getPositionName(currentDefault)
        const ok = await confirmDialog({
          title: '是否更新默认岗位？',
          message: `你的当前默认岗位是「${currentName}」，测试推荐为「${recName}」。是否将默认岗位修改为「${recName}」？`,
          confirmText: '修改',
          cancelText: '保持原样'
        })
        if (ok) {
          await updateMe({ target_position: recPos }).catch(e => console.warn(e))
          await updateSettings({ default_position: recPos }).catch(e => console.warn(e))
          showToast(`「${recName}」已设置为默认岗位`)
        }
      }
    }

    await getSettings().catch(() => {})

    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (e) {
    console.error('提交失败', e)
    showToast(e.message || '提交失败，请重试')
  } finally {
    submitting.value = false
  }
}

const resetTest = () => {
  result.value = null
  questions.value.forEach(q => {
    answers[q.id] = null
  })
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const startInterview = (positionCode) => {
  router.push({
    path: '/main/interview/detail',
    query: { code: positionCode }
  })
}

const goBack = () => {
  if (route.query.from === 'profile') {
    router.push('/main/profile')
  } else {
    sessionStorage.removeItem('hasChosenModule')
    router.push('/launcher')
  }
}

onMounted(() => {
  loadQuestions()
})
</script>

<style scoped>
.career-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) 0 var(--space-4);
  position: sticky;
  top: 0;
  background: var(--bg-page);
  z-index: 10;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2) var(--space-1) var(--space-1);
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: color var(--duration-fast) var(--ease-out);
}

.back-btn:hover { color: var(--text-primary); background: var(--gray-100); }
.page-title { margin: 0; font-size: var(--text-base); font-weight: var(--font-bold); color: var(--text-primary); }
.header-spacer { width: 60px; }

.state-card { padding: var(--space-12) var(--space-5); text-align: center; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-lg); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.intro-text { margin-bottom: var(--space-6); padding: var(--space-4); background: var(--bg-card); border-radius: var(--radius-md); border: 1px solid var(--border-default); }
.intro-text p { margin: 0; font-size: var(--text-sm); color: var(--text-secondary); line-height: var(--leading-relaxed); }
.intro-hint { margin-top: var(--space-2) !important; font-size: var(--text-xs) !important; color: var(--text-tertiary) !important; }

.question-group { margin-bottom: var(--space-8); }
.group-title { margin: 0 0 var(--space-4) 0; font-size: var(--text-lg); font-weight: var(--font-bold); color: var(--text-primary); padding-bottom: var(--space-2); border-bottom: 2px solid var(--border-strong); }
.question-list { display: flex; flex-direction: column; gap: var(--space-4); }
.question-card { padding: var(--space-4); background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-lg); }
.q-header { display: flex; align-items: flex-start; gap: var(--space-3); margin-bottom: var(--space-3); }
.q-index { width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; background: var(--gray-200); color: var(--text-secondary); font-size: 10px; font-weight: var(--font-bold); border-radius: var(--radius-full); flex-shrink: 0; margin-top: 2px; }
.q-text { margin: 0; font-size: var(--text-sm); font-weight: var(--font-medium); color: var(--text-primary); line-height: var(--leading-normal); }

.options-list { display: flex; flex-direction: column; gap: 2px; }
.option-item { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-3); background: var(--gray-50); border: 1px solid transparent; border-radius: var(--radius-md); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); user-select: none; }
.option-item:hover { background: var(--gray-100); }
.option-item.selected { background: var(--bg-card); border-color: var(--gray-900); box-shadow: var(--shadow-xs); }
.radio-circle { width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--border-strong); display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all var(--duration-fast) var(--ease-out); }
.option-item.selected .radio-circle { border-color: var(--gray-900); }
.radio-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--gray-900); opacity: 0; transform: scale(0.5); transition: all var(--duration-fast) var(--ease-out); }
.option-item.selected .radio-dot { opacity: 1; transform: scale(1); }
.opt-val { font-size: var(--text-xs); font-weight: var(--font-bold); color: var(--text-primary); width: 12px; }
.opt-label { font-size: var(--text-xs); color: var(--text-secondary); line-height: var(--leading-normal); }
.option-item.selected .opt-label { color: var(--text-primary); font-weight: var(--font-medium); }

.submit-bar { text-align: center; margin-top: var(--space-8); padding-bottom: var(--space-6); }
.submit-btn { width: 100%; padding: 13px var(--space-4); background: var(--gray-900); color: var(--text-invert); border: none; border-radius: var(--radius-md); font-size: var(--text-base); font-weight: var(--font-semibold); cursor: pointer; transition: background var(--duration-fast) var(--ease-out); }
.submit-btn:hover:not(:disabled) { background: var(--gray-800); }
.submit-btn:active:not(:disabled) { background: var(--gray-950); }
.submit-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.result-section { display: flex; flex-direction: column; gap: var(--space-5); }
.animate-up { animation: fadeInUp 0.4s var(--ease-out); }
@keyframes fadeInUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

.recommended-card { padding: var(--space-8) var(--space-6); background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-lg); text-align: center; box-shadow: var(--shadow-md); }

.result-icon-wrap { 
  width: 64px; 
  height: 64px; 
  margin: 0 auto var(--space-4); 
  display: flex; 
  align-items: center; 
  justify-content: center; 
  background: var(--gray-100); 
  color: var(--gray-900); 
  border-radius: var(--radius-lg); 
}

.result-title { margin: 0 0 var(--space-2) 0; font-size: var(--text-sm); color: var(--text-secondary); }
.result-position { margin: 0 0 var(--space-2) 0; font-size: var(--text-2xl); font-weight: var(--font-bold); color: var(--text-primary); letter-spacing: var(--tracking-tight); }
.index-badge { display: inline-block; padding: 4px 12px; background: var(--gray-100); border-radius: var(--radius-full); font-size: var(--text-xs); color: var(--text-secondary); margin-bottom: var(--space-4); }
.index-badge strong { color: var(--text-primary); font-size: var(--text-sm); }
.result-reason { margin: 0 0 var(--space-5) 0; font-size: var(--text-sm); color: var(--text-tertiary); line-height: var(--leading-relaxed); padding: 0 var(--space-2); }

.metrics-row { display: flex; justify-content: space-around; padding: var(--space-3); background: var(--gray-50); border-radius: var(--radius-md); margin-bottom: var(--space-6); }
.metric-item { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.m-val { font-size: var(--text-base); font-weight: var(--font-bold); color: var(--text-primary); }
.m-label { font-size: var(--text-xs); color: var(--text-tertiary); }

.start-btn { width: 100%; display: flex; align-items: center; justify-content: center; gap: var(--space-2); padding: 13px var(--space-4); background: var(--gray-900); color: var(--text-invert); border: none; border-radius: var(--radius-md); font-size: var(--text-base); font-weight: var(--font-semibold); cursor: pointer; transition: background var(--duration-fast) var(--ease-out); }
.start-btn:hover { background: var(--gray-800); }

.signal-card { padding: var(--space-4) var(--space-5); background: var(--bg-card); border: 1px dashed var(--border-strong); border-radius: var(--radius-lg); }
.signal-header { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); color: var(--text-primary); font-weight: var(--font-semibold); font-size: var(--text-sm); }
.signal-text { margin: 0; font-size: var(--text-sm); color: var(--text-secondary); line-height: var(--leading-relaxed); }

.alt-section { padding: 0 var(--space-2); }
.alt-title { margin: 0 0 var(--space-3) 0; font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary); }
.alt-list { display: flex; flex-direction: column; gap: var(--space-3); }
.alt-item { display: flex; align-items: center; gap: var(--space-3); }
.alt-name { width: 100px; font-size: var(--text-sm); color: var(--text-secondary); }
.alt-bar-wrap { flex: 1; height: 8px; background: var(--gray-200); border-radius: var(--radius-full); overflow: hidden; }
.alt-bar { height: 100%; background: var(--gray-400); border-radius: var(--radius-full); }
.alt-score { width: 24px; text-align: right; font-size: var(--text-xs); font-weight: var(--font-semibold); color: var(--text-primary); }

.guide-text { margin: 0; padding: var(--space-3) var(--space-4); background: var(--gray-50); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); font-size: var(--text-xs); color: var(--text-tertiary); line-height: var(--leading-relaxed); text-align: center; }
.retake-btn { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-2); margin: var(--space-2) auto 0; padding: var(--space-2) var(--space-4); background: transparent; color: var(--text-secondary); border: none; font-size: var(--text-sm); cursor: pointer; transition: color var(--duration-fast) var(--ease-out); }
.retake-btn:hover { color: var(--text-primary); }

@media (min-width: 1024px) {
  .career-container { max-width: 800px; padding: 0 0 var(--space-12); }
  .question-card { padding: var(--space-5); }
  .q-text { font-size: var(--text-base); }
  .options-list { flex-direction: row; flex-wrap: wrap; }
  .option-item { flex: 1; min-width: 120px; justify-content: center; }
  .result-position { font-size: var(--text-3xl); }
}
</style>