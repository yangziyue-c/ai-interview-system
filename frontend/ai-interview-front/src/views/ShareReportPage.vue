<template>
  <div class="share-page">
    <header class="share-header">
      <div class="brand">
        <div class="brand-icon">
          <AppIcon name="audio-lines" :size="20" />
        </div>
        <span class="brand-title">AI 模拟面试</span>
      </div>
      <span class="share-tag">分享报告</span>
    </header>

    <div v-if="loading" class="state-card">
      <AppIcon name="loading" :size="28" class="spin" />
      <p>正在加载分享报告...</p>
    </div>

    <div v-else-if="error" class="state-card">
      <div class="error-icon">
        <AppIcon name="alert" :size="32" />
      </div>
      <h2 class="error-title">{{ errorTitle }}</h2>
      <p class="error-desc">{{ errorDesc }}</p>
      <button class="cta-btn" @click="goHome">返回首页</button>
    </div>

    <div v-else class="report-body">
      <div class="report-header">
        <h1 class="report-title">模拟面试评估报告</h1>
        <p class="report-subtitle">{{ positionName }} · {{ reportDate }}</p>
      </div>

      <div v-if="hasMissingData" class="partial-banner">
        <AppIcon name="alert" :size="16" />
        <span>{{ partialMessage }}</span>
      </div>

      <div class="report-grid">
        <div class="report-col">
          <div class="score-card">
            <span class="score-number">{{ totalScore ?? '—' }}</span>
            <span class="score-label">综合得分</span>
          </div>

          <div class="card">
            <h3 class="card-title">能力维度评估</h3>
            <div ref="radarChartRef" class="chart-container"></div>
          </div>
        </div>

        <div class="report-col">
          <div class="card">
            <div class="section-header">
              <AppIcon name="message" :size="16" />
              <span class="section-title">综合评语</span>
            </div>
            <p class="section-body">{{ summary }}</p>
          </div>

          <div class="card" v-if="strengths.length > 0">
            <div class="section-header">
              <AppIcon name="check-circle" :size="16" />
              <span class="section-title">优点</span>
            </div>
            <ul class="section-list">
              <li v-for="(item, idx) in strengths" :key="idx">{{ item }}</li>
            </ul>
          </div>

          <div class="card" v-if="weaknesses.length > 0">
            <div class="section-header">
              <AppIcon name="alert" :size="16" />
              <span class="section-title">待改进</span>
            </div>
            <ul class="section-list">
              <li v-for="(item, idx) in weaknesses" :key="idx">{{ item }}</li>
            </ul>
          </div>

          <div class="card card-dark" v-if="suggestions.length > 0">
            <div class="section-header">
              <AppIcon name="shield" :size="16" />
              <span class="section-title">改进建议</span>
            </div>
            <ul class="section-list section-list-invert">
              <li v-for="(item, idx) in suggestions" :key="idx">{{ item }}</li>
            </ul>
          </div>
        </div>
      </div>

      <div class="privacy-tip">
        <AppIcon name="info" :size="14" />
        <span>分享内容包含个人信息，请注意隐私</span>
      </div>

      <button class="cta-btn" @click="goHome">
        <AppIcon name="play" :size="16" />
        <span>我也来试试 AI 模拟面试</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import * as echarts from 'echarts'
import AppIcon from '@/components/AppIcon.vue'
import { getSharedReport } from '@/api/report'
import { getPositions, getPositionName } from '@/api/position'

const router = useRouter()
const route = useRoute()

const loading = ref(true)
const error = ref(false)
const errorTitle = ref('链接不存在或已过期')
const errorDesc = ref('请联系分享者重新生成')

const totalScore = ref(null)
const radarData = ref([])
const summary = ref('')
const strengths = ref([])
const weaknesses = ref([])
const suggestions = ref([])
const positionName = ref('')
const reportDate = ref('')
const radarChartRef = ref(null)
let radarChart = null

const isPartial = ref(false)
const missingDimensions = ref([])

const hasMissingData = computed(() => {
  return (
    isPartial.value ||
    missingDimensions.value.length > 0 ||
    totalScore.value === null
  )
})

const partialMessage = computed(() => {
  if (totalScore.value === null) {
    return '本次评分未生成，可能因作答不足或评分服务异常'
  }
  if (missingDimensions.value.length > 0) {
    return `本次评分不完整（${missingDimensions.value.join('、')}未评出）`
  }
  if (isPartial.value) {
    return '本次评分不完整，部分轮次未能完成评分'
  }
  return ''
})

const formatDate = (val) => {
  if (!val) return ''
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  return d.toLocaleDateString('zh-CN')
}

const goHome = () => {
  const token = localStorage.getItem('token')
  router.push(token ? '/main/interview' : '/login')
}

const handleResize = () => {
  radarChart?.resize()
}

const initRadarChart = () => {
  if (!radarChartRef.value) return
  radarChart = echarts.init(radarChartRef.value)

  const option = {
    radar: {
      indicator: [
        { name: '技术水平', max: 100 },
        { name: '逻辑思维', max: 100 },
        { name: '沟通表达', max: 100 },
        { name: '应变能力', max: 100 },
        { name: '岗位匹配', max: 100 }
      ],
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: '#3f3f46', fontSize: 12, fontWeight: 500 },
      splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.08)' } },
      splitArea: { areaStyle: { color: ['rgba(0, 0, 0, 0.02)', 'rgba(0, 0, 0, 0.04)'] } },
      axisLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.10)' } }
    },
    series: [{
      type: 'radar',
      data: [{
        value: radarData.value,
        name: '本次面试',
        areaStyle: { color: 'rgba(24, 24, 27, 0.12)' },
        lineStyle: { color: '#18181b', width: 2 },
        itemStyle: { color: '#18181b' }
      }],
      symbol: 'circle',
      symbolSize: 5
    }]
  }

  radarChart.setOption(option)
  window.addEventListener('resize', handleResize)
}

onMounted(async () => {
  const code = route.params.code
  if (!code) {
    error.value = true
    loading.value = false
    return
  }

  try {
    await getPositions()
  } catch (e) {
    console.warn('加载岗位列表失败，岗位名将显示为 code', e)
  }

  try {
    const data = await getSharedReport(code)

    totalScore.value = data.total_score ?? null

    const DIMENSIONS = [
      { name: '技术水平', value: data.tech_score },
      { name: '逻辑思维', value: data.logic_score },
      { name: '沟通表达', value: data.expression_score },
      { name: '应变能力', value: data.adaptability_score },
      { name: '岗位匹配', value: data.match_score }
    ]
    const missing = []
    radarData.value = DIMENSIONS.map(d => {
      if (d.value === null || d.value === undefined) {
        missing.push(d.name)
        return 0
      }
      return d.value
    })
    missingDimensions.value = missing

    isPartial.value = data.partial === true

    summary.value = data.summary || ''
    strengths.value = data.strengths || []
    weaknesses.value = data.weaknesses || []
    suggestions.value = data.suggestions || []
    positionName.value = getPositionName(data.position)
    reportDate.value = formatDate(data.created_at)

    loading.value = false
    await nextTick()
    initRadarChart()
  } catch (e) {
    console.error('加载分享报告失败', e)

    const isNotFound = e?.code === 40400 || e?.response?.status === 404
    if (isNotFound) {
      errorTitle.value = '链接不存在或已过期'
      errorDesc.value = '请联系分享者重新生成'
    } else {
      errorTitle.value = '加载失败'
      errorDesc.value = '网络异常或服务暂时不可用，请稍后重试'
    }
    error.value = true
    loading.value = false
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (radarChart) {
    radarChart.dispose()
    radarChart = null
  }
})
</script>

<style scoped>
/* 页面容器 */
.share-page {
  height: 100vh;
  overflow-y: auto;
  padding: var(--space-5) var(--space-4) var(--space-8);
  background: var(--gray-950);
  font-family: var(--font-sans);
  box-sizing: border-box;
  color-scheme: dark;
}

/* 顶部品牌条 */
.share-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 600px;
  margin: 0 auto var(--space-5);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.brand-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-50);
  color: var(--gray-950);
  border-radius: var(--radius-md);
  flex-shrink: 0;
}

.brand-title {
  font-size: var(--text-sm);
  font-weight: var(--font-bold);
  color: var(--gray-50);
  letter-spacing: var(--tracking-tight);
}

.share-tag {
  padding: 3px var(--space-3);
  background: var(--gray-800);
  color: var(--gray-300);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  border-radius: var(--radius-full);
  border: 1px solid var(--gray-700);
}

/* 加载 / 错误态 */
.state-card {
  max-width: 500px;
  margin: var(--space-12) auto 0;
  padding: var(--space-10) var(--space-6);
  text-align: center;
  background: var(--gray-900);
  border: 1px solid var(--gray-800);
  border-radius: var(--radius-xl);
}

.state-card p {
  margin: var(--space-3) 0 0 0;
  font-size: var(--text-sm);
  color: var(--gray-500);
}

.spin {
  color: var(--gray-500);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto var(--space-4);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-800);
  color: var(--gray-400);
  border-radius: var(--radius-full);
}

.error-title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--gray-50);
}

.error-desc {
  margin: 0 0 var(--space-6) 0;
  font-size: var(--text-sm);
  color: var(--gray-500);
}

/* 报告主体 */
.report-body {
  max-width: 600px;
  margin: 0 auto;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  padding: var(--space-6) var(--space-5);
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.06),
    0 24px 48px rgba(0, 0, 0, 0.4);
}

.report-header {
  text-align: center;
  padding-bottom: var(--space-5);
}

.report-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.report-subtitle {
  margin: var(--space-1) 0 0 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.partial-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
  background: var(--warning-bg);
  border: 1px solid var(--warning);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.partial-banner :deep(.app-icon) {
  color: var(--warning);
  flex-shrink: 0;
}

/* 移动端单栏布局 */
.report-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.report-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* 分数卡 */
.score-card {
  padding: var(--space-6) var(--space-4);
  background: var(--gray-900);
  color: var(--text-invert);
  border-radius: var(--radius-lg);
  text-align: center;
}

.score-number {
  display: block;
  font-size: 48px;
  font-weight: var(--font-bold);
  line-height: 1.1;
  letter-spacing: var(--tracking-tight);
}

.score-label {
  display: block;
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--gray-400);
}

/* 通用卡片 */
.card {
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.card-title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.chart-container {
  width: 100%;
  height: 240px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  color: var(--text-primary);
}

.section-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
}

.section-body {
  margin: 0;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
}

.section-list {
  margin: 0;
  padding-left: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.section-list li {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
}

.card-dark {
  background: var(--gray-900);
  border-color: var(--gray-900);
  color: var(--text-invert);
}

.card-dark .section-header { color: var(--gray-50); }
.card-dark .section-title { color: var(--gray-50); }
.section-list-invert li { color: var(--gray-300); }

/* 隐私提示 + CTA */
.privacy-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  margin-top: var(--space-4);
  background: var(--gray-50);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.privacy-tip :deep(.app-icon) {
  color: var(--text-disabled);
  flex-shrink: 0;
}

.cta-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 13px var(--space-4);
  margin-top: var(--space-5);
  background: var(--gray-900);
  color: var(--text-invert);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.cta-btn:hover {
  background: var(--gray-800);
}

.cta-btn:active {
  background: var(--gray-950);
  transform: scale(0.98);
}

/* 桌面端左右分栏 */
@media (min-width: 1024px) {
  .share-page {
    padding: var(--space-8) var(--space-6) var(--space-12);
  }

  .share-header {
    max-width: 1000px;
  }

  .report-body {
    max-width: 1000px;
    padding: var(--space-10) var(--space-8);
  }

  .report-title {
    font-size: var(--text-xl);
  }

  .report-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-5);
    align-items: start;
  }

  .report-col {
    gap: var(--space-4);
  }

  .chart-container {
    height: 300px;
  }
}
</style>