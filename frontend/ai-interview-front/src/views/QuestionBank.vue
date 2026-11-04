<template>
  <div class="bank-container" :class="{ 'is-desktop': isDesktop }">
    <div class="bank-header">
      <h2 class="bank-title">题库中心</h2>
      <p class="bank-subtitle">浏览岗位题库，针对性练习</p>
    </div>

    <div class="search-bar">
      <AppIcon name="search" :size="16" class="search-icon" />
      <input
        v-model="keyword"
        type="text"
        class="search-input"
        placeholder="搜索题目关键词..."
        @keyup.enter="applySearch"
      />
      <button
        v-if="keyword"
        class="search-clear"
        @click="clearSearch"
        aria-label="清空"
      >
        <AppIcon name="close" :size="14" />
      </button>
    </div>

    <div class="filter-row">
      <div
        class="filter-chip"
        :class="{ active: filters.position === '' }"
        @click="setFilter('position', '')"
      >
        全部岗位
      </div>
      <div
        v-for="p in allPositions"
        :key="p.code"
        class="filter-chip"
        :class="{ active: filters.position === p.code }"
        @click="setFilter('position', p.code)"
      >
        {{ p.name }}
      </div>
    </div>

    <div class="filter-row">
      <div
        class="filter-chip"
        :class="{ active: filters.difficulty === '' }"
        @click="setFilter('difficulty', '')"
      >
        全部难度
      </div>
      <div
        v-for="d in difficulties"
        :key="d.code"
        class="filter-chip"
        :class="{ active: filters.difficulty === d.code }"
        @click="setFilter('difficulty', d.code)"
      >
        {{ d.label }}
      </div>
    </div>

    <div v-if="!loading" class="result-info">
      共 <strong>{{ total }}</strong> 道题
    </div>

    <div v-if="loading" class="state-card">
      <AppIcon name="loading" :size="28" class="spin" />
      <p>正在加载题目...</p>
    </div>

    <div v-else-if="list.length === 0" class="state-card">
      <AppIcon name="search" :size="28" class="state-icon" />
      <p>没有匹配的题目</p>
      <span class="state-hint">试试换个筛选条件</span>
    </div>

    <div v-else class="question-list">
      <div
        v-for="q in list"
        :key="q.id"
        class="question-card"
        :class="{ expanded: expandedId === q.id }"
      >
        <div class="q-header" @click="toggleExpand(q.id)">
          <div class="q-tags-left">
            <span class="q-tag q-tag-category">{{ q.category }}</span>
            <span class="q-tag q-tag-difficulty" :class="`diff-${q.difficulty}`">
              {{ difficultyLabel(q.difficulty) }}
            </span>
            <span class="q-tag q-tag-stage">{{ q.interview_stage }}</span>
          </div>
          <AppIcon
            name="chevron-right"
            :size="16"
            class="q-chevron"
            :class="{ rotated: expandedId === q.id }"
          />
        </div>

        <p class="q-text" @click="toggleExpand(q.id)">{{ q.question }}</p>

        <div class="q-keywords" v-if="splitKeywords(q.keywords).length > 0">
          <span
            v-for="(kw, idx) in splitKeywords(q.keywords)"
            :key="idx"
            class="q-keyword"
          >
            {{ kw }}
          </span>
        </div>

        <transition name="expand">
          <div v-if="expandedId === q.id" class="q-detail">
            <div class="detail-section" v-if="q.basic_score_points">
              <div class="detail-label">基础得分点</div>
              <p class="detail-text">{{ q.basic_score_points }}</p>
            </div>
            <div class="detail-section" v-if="q.advanced_score_points">
              <div class="detail-label">进阶得分点</div>
              <p class="detail-text">{{ q.advanced_score_points }}</p>
            </div>
            <div class="detail-section" v-if="q.follow_up_l1">
              <div class="detail-label">追问示例</div>
              <p class="detail-text">{{ cleanFollowUp(q.follow_up_l1) }}</p>
            </div>
            <div class="detail-section" v-if="q.calibration_anchor">
              <div class="detail-label">评分参考</div>
              <p class="detail-text">{{ q.calibration_anchor }}</p>
            </div>
            <div class="detail-meta">
              <span v-if="q.exam_priority">考点优先级：{{ q.exam_priority }}</span>
              <span v-if="q.suggested_minutes">建议时长：{{ q.suggested_minutes }} 分钟</span>
            </div>
          </div>
        </transition>
      </div>
    </div>

    <button
      v-if="!loading && list.length < total"
      class="load-more-btn"
      @click="loadMore"
      :disabled="loadingMore"
    >
      {{ loadingMore ? '加载中...' : `加载更多（剩余 ${total - list.length} 题）` }}
    </button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getQuestions, DIFFICULTIES } from '@/api/question'
import { getPositions } from '@/api/position'

const isDesktop = useMediaQuery('(min-width: 1024px)')

const allPositions = ref([])
const difficulties = DIFFICULTIES

const filters = ref({
  position: '',
  difficulty: '',
  category: '',
  stage: '',
  q: ''
})
const keyword = ref('')

const list = ref([])
const total = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const expandedId = ref(null)

const PAGE_SIZE = 10

const difficultyLabel = (code) => {
  const d = difficulties.find(x => x.code === code)
  return d ? d.label : code
}

const splitKeywords = (str) => {
  if (!str) return []
  return str.split('\n').map(s => s.trim()).filter(Boolean)
}

// 追问原文带 [追问] 标记，只展示追问部分
const cleanFollowUp = (str) => {
  if (!str) return ''
  const lines = str.split('\n')
  const followUpLine = lines.find(l => l.startsWith('[追问]'))
  return followUpLine ? followUpLine.replace('[追问]', '').trim() : str
}

const buildParams = (offset) => {
  const params = { offset, limit: PAGE_SIZE }
  if (filters.value.position) params.position = filters.value.position
  if (filters.value.difficulty) params.difficulty = filters.value.difficulty
  if (filters.value.category) params.category = filters.value.category
  if (filters.value.stage) params.stage = filters.value.stage
  if (filters.value.q) params.q = filters.value.q
  return params
}

const loadFirst = async () => {
  loading.value = true
  expandedId.value = null
  try {
    const res = await getQuestions(buildParams(0))
    list.value = res.items
    total.value = res.total
  } catch (e) {
    console.error('加载题库失败', e)
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const loadMore = async () => {
  if (loadingMore.value) return
  loadingMore.value = true
  try {
    const res = await getQuestions(buildParams(list.value.length))
    list.value = list.value.concat(res.items)
    total.value = res.total
  } catch (e) {
    console.error('加载更多失败', e)
  } finally {
    loadingMore.value = false
  }
}

const setFilter = (key, value) => {
  if (filters.value[key] === value) return
  filters.value[key] = value
  loadFirst()
}

const applySearch = () => {
  filters.value.q = keyword.value.trim()
  loadFirst()
}

const clearSearch = () => {
  keyword.value = ''
  filters.value.q = ''
  loadFirst()
}

const toggleExpand = (id) => {
  expandedId.value = expandedId.value === id ? null : id
}

onMounted(async () => {
  await Promise.all([
    getPositions().then(p => { allPositions.value = p }),
    loadFirst()
  ])
})
</script>

<style scoped>
/* 容器 */
.bank-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

/* 页面标题 */
.bank-header {
  padding: var(--space-3) 0 var(--space-4);
  animation: fadeInUp 0.35s var(--ease-out);
}

.bank-title {
  margin: 0 0 var(--space-2) 0;
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.bank-subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 搜索框 */
.search-bar {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: var(--space-3);
}

.search-icon {
  position: absolute;
  left: var(--space-3);
  color: var(--text-tertiary);
  pointer-events: none;
}

.search-input {
  flex: 1;
  padding: 10px var(--space-3) 10px 38px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--bg-card);
  outline: none;
  box-sizing: border-box;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.search-input::placeholder {
  color: var(--text-disabled);
}

.search-input:focus {
  border-color: var(--gray-900);
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.06);
}

.search-clear {
  position: absolute;
  right: 6px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.search-clear:hover {
  background: var(--gray-100);
  color: var(--text-primary);
}

/* 筛选行 */
.filter-row {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  overflow-x: auto;
  padding-bottom: var(--space-1);
  scrollbar-width: none;
}

.filter-row::-webkit-scrollbar { display: none; }

.filter-chip {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition: border-color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.filter-chip:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.filter-chip.active {
  background: var(--gray-900);
  border-color: var(--gray-900);
  color: var(--text-invert);
}

/* 结果统计 */
.result-info {
  padding: var(--space-3) 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.result-info strong {
  color: var(--text-primary);
  font-weight: var(--font-semibold);
}

/* 状态卡片 */
.state-card {
  padding: var(--space-12) var(--space-5);
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.state-card p {
  margin: var(--space-3) 0 var(--space-1) 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.state-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.state-icon {
  color: var(--text-disabled);
}

.spin {
  color: var(--text-tertiary);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 题目列表 */
.question-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.question-card {
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  transition: border-color var(--duration-fast) var(--ease-out);
}

.question-card:hover {
  border-color: var(--border-strong);
}

.question-card.expanded {
  border-color: var(--gray-900);
}

.q-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  cursor: pointer;
  margin-bottom: var(--space-3);
}

.q-tags-left {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.q-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: var(--font-medium);
  line-height: 1.6;
  white-space: nowrap;
}

.q-tag-category {
  background: var(--gray-100);
  color: var(--text-secondary);
}

.q-tag-stage {
  background: var(--gray-100);
  color: var(--text-secondary);
}

.q-tag-difficulty.diff-easy {
  background: var(--success-bg);
  color: var(--success);
}

.q-tag-difficulty.diff-medium {
  background: var(--warning-bg);
  color: var(--warning);
}

.q-tag-difficulty.diff-hard {
  background: var(--danger-bg);
  color: var(--danger);
}

.q-chevron {
  color: var(--text-disabled);
  flex-shrink: 0;
  transition: transform var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.q-chevron.rotated {
  transform: rotate(90deg);
  color: var(--text-primary);
}

.q-text {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-primary);
  cursor: pointer;
  font-weight: var(--font-medium);
}

.q-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.q-keyword {
  padding: 2px var(--space-2);
  background: var(--gray-50);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  font-size: 10px;
  color: var(--text-tertiary);
}

/* 展开详情 */
.q-detail {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.detail-label {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-tertiary);
  letter-spacing: var(--tracking-wide);
}

.detail-text {
  margin: 0;
  padding: var(--space-3);
  background: var(--gray-50);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding-top: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* 展开动画 */
.expand-enter-active,
.expand-leave-active {
  transition: opacity 0.2s var(--ease-out);
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
}

/* 加载更多 */
.load-more-btn {
  width: 100%;
  margin-top: var(--space-4);
  padding: 11px var(--space-4);
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.load-more-btn:hover:not(:disabled) {
  border-color: var(--gray-900);
  background: var(--gray-50);
}

.load-more-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 桌面端 */
@media (min-width: 1024px) {
  .bank-container {
    max-width: 1000px;
    padding: 0 0 var(--space-12);
  }

  .bank-title {
    font-size: var(--text-2xl);
  }

  .question-list {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
  }

  .question-card.expanded {
    grid-column: 1 / -1;
  }
}
</style>