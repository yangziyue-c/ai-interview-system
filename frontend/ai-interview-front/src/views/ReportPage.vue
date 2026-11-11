<template>
  <div class="report-container" :class="{ 'is-desktop': isDesktop }">
    <div ref="captureRef" class="report-capture">
      <div class="report-header animate-header">
        <div class="header-icon">
          <AppIcon name="file" :size="22" />
        </div>
        <div>
          <h2 class="header-title">模拟面试评估报告</h2>
          <p class="header-subtitle">{{ positionName }} · {{ reportDate }}</p>
        </div>
      </div>

      <div v-if="!loading && hasMissingData" class="partial-banner">
        <AppIcon name="alert" :size="16" />
        <span>{{ partialMessage }}</span>
      </div>

      <div v-if="loading" class="state-card">
        <AppIcon name="loading" :size="28" class="spin" />
        <p>正在生成评估报告...</p>
      </div>

      <div v-else class="report-grid">
        <div class="score-card animate-card">
          <span class="score-number">{{ totalScore ?? '—' }}</span>
          <span class="score-label">综合得分</span>
        </div>

        <div class="report-col">
          <div class="card animate-card">
            <h3 class="card-title">能力维度评估</h3>
            <div ref="radarChartRef" class="chart-container"></div>
          </div>

          <div class="card animate-card" v-if="growthData.length > 0">
            <h3 class="card-title">
              成长曲线 <span class="card-title-sub">（{{ positionName }}）</span>
            </h3>
            <div ref="growthChartRef" class="chart-container"></div>
          </div>
        </div>

        <div class="report-col">
          <div class="card animate-card">
            <div class="section-header">
              <AppIcon name="message" :size="16" />
              <span class="section-title">综合评语</span>
            </div>
            <p class="section-body">{{ summary }}</p>
          </div>

          <div class="sw-wrapper animate-card">
            <div class="card">
              <div class="section-header">
                <AppIcon name="check-circle" :size="16" />
                <span class="section-title">优点</span>
              </div>
              <ul class="section-list">
                <li v-for="(item, idx) in strengths" :key="idx">{{ item }}</li>
              </ul>
            </div>

            <div class="card">
              <div class="section-header">
                <AppIcon name="alert" :size="16" />
                <span class="section-title">待改进</span>
              </div>
              <ul class="section-list">
                <li v-for="(item, idx) in weaknesses" :key="idx">{{ item }}</li>
              </ul>
            </div>
          </div>

          <div class="card card-dark animate-card">
            <div class="section-header">
              <AppIcon name="lightbulb" :size="16" />
              <span class="section-title">学习计划</span>
              <span v-if="studyPlanTotalMinutes > 0" class="section-title-extra">
                约 {{ studyPlanTotalMinutes }} 分钟
              </span>
            </div>

            <div v-if="studyPlanLoading" class="plan-loading">
              <AppIcon name="loading" :size="16" class="spin" />
              <span>加载中...</span>
            </div>

            <div v-else-if="studyPlanList.length === 0" class="plan-empty">
              <p>{{ studyPlanNotice || '暂无学习建议' }}</p>
            </div>

            <ul v-else class="plan-list">
              <li
                v-for="(kp, idx) in studyPlanList"
                :key="idx"
                class="plan-item"
              >
                <div class="plan-item-header">
                  <span class="plan-item-title">
                    {{ kp.title || `知识点 ${idx + 1}` }}
                  </span>
                  <span v-if="kp.question_count" class="plan-item-count">
                    {{ kp.question_count }} 题 · 约 {{ kp.total_minutes || 0 }} 分钟
                  </span>
                </div>
                <p v-if="kp.suggestion" class="plan-item-suggestion">
                  {{ kp.suggestion }}
                </p>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!loading && canViewQaHistory" class="qa-history-btn-wrapper">
      <button class="qa-history-btn" @click="goQaHistory">
        <AppIcon name="message" :size="16" />
        <span>查看具体面试问答</span>
      </button>
    </div>

    <div v-if="!loading" class="action-buttons animate-card">
      <button class="btn btn-secondary" @click="fromHistory ? goProfile() : goHome()">
        {{ fromHistory ? '返回个人中心' : '返回首页' }}
      </button>
      <button class="btn btn-secondary" @click="showShareMenu = true">
        <AppIcon name="link" :size="14" />
        <span>分享</span>
      </button>
      <button class="btn btn-primary" @click="retryInterview" :disabled="retrying">
        {{ retrying ? '检查中...' : '重新面试' }}
      </button>
    </div>

    <div v-if="showShareMenu" class="share-menu-overlay" @click.self="showShareMenu = false">
      <div class="share-menu">
        <div class="share-option" @click="handleShareImage">
          <div class="option-icon">
            <AppIcon name="file" :size="20" />
          </div>
          <div class="option-text">
            <p class="option-title">保存为图片</p>
            <p class="option-desc">生成长图，可保存到相册</p>
          </div>
        </div>
        <div class="share-option" @click="handleShareLink">
          <div class="option-icon">
            <AppIcon name="link" :size="20" />
          </div>
          <div class="option-text">
            <p class="option-title">复制分享链接</p>
            <p class="option-desc">生成链接，对方免登录查看</p>
          </div>
        </div>
        <button class="share-menu-cancel" @click="showShareMenu = false">取消</button>
      </div>
    </div>

    <div v-if="showShareModal" class="share-overlay" @click.self="showShareModal = false">
      <div class="share-modal">
        <p class="share-tip">长按图片保存到相册</p>
        <img :src="shareImageUrl" class="share-image" />
        <button class="share-close-btn" @click="showShareModal = false">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import * as echarts from 'echarts'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getReport, getGrowth, shareReport, getStudyPlan } from '@/api/report'
import { getInterviewDetail, checkInProgress } from '@/api/interview'
import { getPositionName } from '@/api/position'
import { showToast } from '@/utils/toast'

const router = useRouter()
const route = useRoute()

const isDesktop = useMediaQuery('(min-width: 1024px)')

const fromHistory = computed(() => route.query.fromHistory === 'true')

const loading = ref(true)
const totalScore = ref(null)
const radarData = ref([])
const summary = ref('')
const strengths = ref([])
const weaknesses = ref([])
const growthData = ref([])
const reportDate = ref('')
const position = ref('')
const positionName = ref('')
const interviewId = ref(null)
const qaCount = ref(0)

const isPartial = ref(false)
const missingDimensions = ref([])

const studyPlanList = ref([])
const studyPlanNotice = ref('')
const studyPlanLoading = ref(false)

const retrying = ref(false)

const studyPlanTotalMinutes = computed(() => {
  return studyPlanList.value.reduce((sum, kp) => sum + (kp.total_minutes || 0), 0)
})

const radarChartRef = ref(null)
const growthChartRef = ref(null)
let radarChart = null
let growthChart = null

const captureRef = ref(null)
const isExporting = ref(false)
const shareImageUrl = ref('')
const showShareModal = ref(false)
const showShareMenu = ref(false)

const canViewQaHistory = computed(() => qaCount.value > 0)

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

const goQaHistory = () => {
  if (!interviewId.value) return
  router.push({
    path: '/main/qa-history',
    query: {
      recordId: interviewId.value,
      fromHistory: fromHistory.value ? 'true' : 'false'
    }
  })
}

const formatDate = (val) => {
  if (!val) return ''
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  return d.toLocaleDateString('zh-CN')
}

const handleShareImage = () => {
  showShareMenu.value = false
  exportReport()
}

const handleShareLink = async () => {
  showShareMenu.value = false

  try {
    const res = await shareReport(interviewId.value)
    const url = res.share_url

    let copied = false
    try {
      await navigator.clipboard.writeText(url)
      copied = true
    } catch (e) {
      const textarea = document.createElement('textarea')
      textarea.value = url
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      try {
        document.execCommand('copy')
        copied = true
      } catch (e2) {
        copied = false
      }
      document.body.removeChild(textarea)
    }

    if (copied) {
      showToast('链接已复制，分享给好友吧')
    } else {
      alert(`请手动复制链接：\n${url}`)
    }
  } catch (e) {
    console.error('生成分享链接失败', e)
    showToast('生成链接失败，请重试')
  }
}

const exportReport = async () => {
  if (!captureRef.value || isExporting.value) return
  isExporting.value = true

  const restoreTasks = []

  try {
    const html2canvas = (await import('html2canvas')).default

    const replaceChartWithImage = (chartInstance, chartRef) => {
      if (!chartInstance || !chartRef.value) return
      const dataUrl = chartInstance.getDataURL({
        type: 'png',
        pixelRatio: 2,
        backgroundColor: '#ffffff'
      })
      const img = document.createElement('img')
      img.src = dataUrl
      img.style.width = '100%'
      img.style.height = '100%'
      img.style.display = 'block'
      const parent = chartRef.value.parentNode
      chartRef.value.style.display = 'none'
      parent.appendChild(img)
      restoreTasks.push(() => {
        chartRef.value.style.display = ''
        if (img.parentNode) img.parentNode.removeChild(img)
      })
    }

    replaceChartWithImage(radarChart, radarChartRef)
    replaceChartWithImage(growthChart, growthChartRef)

    const gridEl = captureRef.value.querySelector('.report-grid')
    if (gridEl) {
      const originalDisplay = gridEl.style.display
      const originalGridTemplate = gridEl.style.gridTemplateColumns
      const originalGap = gridEl.style.gap
      gridEl.style.display = 'flex'
      gridEl.style.flexDirection = 'column'
      gridEl.style.gridTemplateColumns = ''
      gridEl.style.gap = '16px'
      restoreTasks.push(() => {
        gridEl.style.display = originalDisplay
        gridEl.style.gridTemplateColumns = originalGridTemplate
        gridEl.style.gap = originalGap
        gridEl.style.flexDirection = ''
      })
    }

    const animatedEls = captureRef.value.querySelectorAll('.animate-card, .animate-header')
    animatedEls.forEach(el => {
      const originalAnimation = el.style.animation
      const originalOpacity = el.style.opacity
      const originalTransform = el.style.transform
      el.style.animation = 'none'
      el.style.opacity = '1'
      el.style.transform = 'none'
      restoreTasks.push(() => {
        el.style.animation = originalAnimation
        el.style.opacity = originalOpacity
        el.style.transform = originalTransform
      })
    })

    await new Promise(r => requestAnimationFrame(r))
    await new Promise(r => setTimeout(r, 100))

    const canvas = await html2canvas(captureRef.value, {
      backgroundColor: '#fafafa',
      scale: 2,
      useCORS: true,
      logging: false,
      width: captureRef.value.scrollWidth,
      height: captureRef.value.scrollHeight
    })

    const dataUrl = canvas.toDataURL('image/png')
    restoreTasks.forEach(task => task())

    if (isDesktop.value) {
      const link = document.createElement('a')
      link.download = `面试报告_${positionName.value}_${reportDate.value.replace(/\//g, '-')}.png`
      link.href = dataUrl
      link.click()
      showToast('图片已保存到下载文件夹')
    } else {
      shareImageUrl.value = dataUrl
      showShareModal.value = true
    }
  } catch (e) {
    console.error('导出图片失败:', e)
    showToast('导出图片失败，请重试')
    restoreTasks.forEach(task => task())
  } finally {
    isExporting.value = false
  }
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
        value: radarData.value.map(item => item.value),
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
  window.addEventListener('resize', handleChartResize)
}

const handleChartResize = () => {
  radarChart?.resize()
  growthChart?.resize()
}

const initGrowthChart = () => {
  if (!growthChartRef.value || growthData.value.length === 0) return
  growthChart = echarts.init(growthChartRef.value)

  const option = {
    grid: { left: 36, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: growthData.value.map(item => item.date),
      axisLine: { lineStyle: { color: '#e4e4e7' } },
      axisTick: { show: false },
      axisLabel: { color: '#71717a', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      min: 40,
      max: 100,
      splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.06)' } },
      axisLabel: { color: '#71717a', fontSize: 11 }
    },
    series: [{
      type: 'line',
      data: growthData.value.map(item => item.score),
      smooth: true,
      lineStyle: { color: '#18181b', width: 2 },
      areaStyle: { color: 'rgba(24, 24, 27, 0.06)' },
      itemStyle: { color: '#18181b' },
      symbol: 'circle',
      symbolSize: 6,
      markLine: {
        silent: true,
        symbol: 'none',
        label: { color: '#71717a', fontSize: 11, formatter: '平均 {c}', position: 'insideEndTop' },
        lineStyle: { color: '#a1a1aa', type: 'dashed' },
        data: [{
          yAxis: Math.round(
            growthData.value.reduce((sum, d) => sum + d.score, 0) / growthData.value.length
          )
        }]
      }
    }]
  }

  growthChart.setOption(option)
}

const goHome = () => router.push('/main/interview')
const goProfile = () => router.push('/main/profile')

const retryInterview = async () => {
  if (retrying.value) return
  retrying.value = true

  try {
    const inProgress = await checkInProgress()
    if (inProgress) {
      showToast('你有未完成的面试，请先去个人中心继续或结束')
      setTimeout(() => {
        router.push('/main/profile')
      }, 1500)
      return
    }

    router.push({
      path: '/main/interview/detail',
      query: { code: position.value }
    })
  } catch (e) {
    console.error('检查面试状态失败', e)
    router.push({
      path: '/main/interview/detail',
      query: { code: position.value }
    })
  } finally {
    retrying.value = false
  }
}

const loadGrowth = async () => {
  try {
    const raw = await getGrowth({ position: position.value })
    growthData.value = raw.map(item => ({
      date: formatDate(item.finished_at),
      score: item.total_score
    }))
  } catch (e) {
    console.error('加载成长曲线失败', e)
    growthData.value = []
  }
}

const loadStudyPlan = async () => {
  if (!interviewId.value) return

  studyPlanLoading.value = true
  try {
    const data = await getStudyPlan({ interviewId: interviewId.value })
    studyPlanNotice.value = data.notice || ''
    studyPlanList.value = data.knowledge_points || []
  } catch (e) {
    console.error('加载学习计划失败', e)
    studyPlanNotice.value = '学习计划加载失败'
    studyPlanList.value = []
  } finally {
    studyPlanLoading.value = false
  }
}

onMounted(async () => {
  const recordId = route.query.recordId
  if (!recordId) {
    console.warn('缺少报告参数，跳回岗位大厅')
    router.replace('/main/interview')
    return
  }

  await new Promise(resolve => setTimeout(resolve, 400))

  try {
    const [report, detail] = await Promise.all([
      getReport(recordId),
      getInterviewDetail(recordId).catch(e => {
        console.warn('获取面试详情失败（不影响报告）', e)
        return null
      })
    ])

    interviewId.value = report.interview_id
    position.value = report.position
    positionName.value = getPositionName(report.position)

    totalScore.value = report.total_score ?? null

    const DIMENSIONS = [
      { name: '技术水平', value: report.tech_score },
      { name: '逻辑思维', value: report.logic_score },
      { name: '沟通表达', value: report.expression_score },
      { name: '应变能力', value: report.adaptability_score },
      { name: '岗位匹配', value: report.match_score }
    ]

    const missing = []
    radarData.value = DIMENSIONS.map(d => {
      if (d.value === null || d.value === undefined) {
        missing.push(d.name)
        return { name: d.name, value: 0 }
      }
      return { name: d.name, value: d.value }
    })
    missingDimensions.value = missing

    isPartial.value = report.partial === true

    summary.value = report.summary || ''
    strengths.value = report.strengths || []
    weaknesses.value = report.weaknesses || []
    reportDate.value = formatDate(report.created_at)

    qaCount.value = detail?.qa_records?.length || 0

    await loadGrowth()

    loading.value = false
    await nextTick()
    initRadarChart()
    initGrowthChart()

    loadStudyPlan()
  } catch (e) {
    console.error('加载报告失败', e)
    showToast('报告加载失败')
    setTimeout(() => router.replace('/main/interview'), 2000)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleChartResize)

  if (radarChart) {
    radarChart.dispose()
    radarChart = null
  }
  if (growthChart) {
    growthChart.dispose()
    growthChart = null
  }
})
</script>

<style scoped>
/* 容器 */
.report-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

.report-capture {
  width: 100%;
}

/* 头部 */
.report-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0 var(--space-4);
}

.header-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  flex-shrink: 0;
}

.header-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.header-subtitle {
  margin: 2px 0 0 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.partial-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-3);
  background: var(--warning-bg);
  border: 1px solid var(--warning);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
  animation: fadeInUp 0.3s var(--ease-out);
}

.partial-banner :deep(.app-icon) {
  color: var(--warning);
  flex-shrink: 0;
}

/* 加载 */
.state-card {
  padding: var(--space-12) var(--space-5);
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.state-card p {
  margin: var(--space-3) 0 0 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.spin {
  color: var(--text-tertiary);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 报告网格 */
.report-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.report-col {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.score-card {
  padding: var(--space-8) var(--space-5) var(--space-6);
  background: var(--gray-900);
  color: var(--text-invert);
  border-radius: var(--radius-lg);
  text-align: center;
  opacity: 0;
  animation: fadeInUp 0.35s var(--ease-out) forwards;
}

.score-number {
  display: block;
  font-size: 56px;
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

.card {
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  opacity: 0;
  animation: fadeInUp 0.35s var(--ease-out) forwards;
}

.animate-header {
  opacity: 0;
  animation: fadeInUp 0.35s var(--ease-out) forwards;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.card-title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.card-title-sub {
  font-size: var(--text-xs);
  font-weight: var(--font-normal);
  color: var(--text-tertiary);
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

.section-title-extra {
  margin-left: auto;
  font-size: var(--text-xs);
  font-weight: var(--font-normal);
  color: var(--gray-400);
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

.sw-wrapper {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.card-dark {
  background: var(--gray-900);
  border-color: var(--gray-900);
  color: var(--text-invert);
}

.card-dark .section-header { color: var(--gray-50); }
.card-dark .section-title { color: var(--gray-50); }
.section-list-invert li { color: var(--gray-300); }

/* 学习计划列表 */
.plan-loading,
.plan-empty {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) 0;
  font-size: var(--text-sm);
  color: var(--gray-400);
}

.plan-empty p {
  margin: 0;
  line-height: var(--leading-relaxed);
}

.plan-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.report-container.is-desktop .plan-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: var(--space-2);
}

.report-container.is-desktop .plan-list::-webkit-scrollbar {
  width: 6px;
}

.report-container.is-desktop .plan-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
  border-radius: 3px;
}

.report-container.is-desktop .plan-list::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.32);
}

.report-container.is-desktop .plan-list {
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.18) transparent;
}

.plan-item {
  padding: var(--space-3) 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.plan-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.plan-item-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.plan-item-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--gray-50);
}

.plan-item-count {
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--gray-400);
}

.plan-item-suggestion {
  margin: 0;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--gray-300);
}

/* 查看问答历史按钮 */
.qa-history-btn-wrapper {
  margin-top: var(--space-4);
}

.qa-history-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 13px var(--space-4);
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

.qa-history-btn:hover {
  border-color: var(--gray-900);
  background: var(--gray-50);
}

/* 底部按钮 */
.action-buttons {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 11px var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
  white-space: nowrap;
}

.btn:active:not(:disabled) { transform: scale(0.98); }

.btn-primary {
  background: var(--gray-900);
  color: var(--text-invert);
  border: 1px solid var(--gray-900);
}

.btn-primary:hover:not(:disabled) { background: var(--gray-800); border-color: var(--gray-800); }

.btn-secondary {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-secondary:hover:not(:disabled) {
  border-color: var(--border-strong);
  background: var(--gray-50);
}

.btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 分享菜单 */
.share-menu-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  z-index: 999;
  animation: fadeIn 0.2s var(--ease-out);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.share-menu {
  width: 100%;
  max-width: 500px;
  background: var(--bg-card);
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  padding: var(--space-5) var(--space-4) calc(var(--space-4) + env(safe-area-inset-bottom));
  animation: slideUp 0.25s var(--ease-out);
}

@keyframes slideUp {
  from { transform: translateY(100%); }
  to   { transform: translateY(0); }
}

.share-option {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.share-option:hover {
  background: var(--gray-50);
}

.option-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  flex-shrink: 0;
}

.option-text {
  flex: 1;
  min-width: 0;
}

.option-title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.option-desc {
  margin: 2px 0 0 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.share-menu-cancel {
  width: 100%;
  margin-top: var(--space-2);
  padding: 11px;
  background: var(--gray-50);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.share-menu-cancel:hover {
  background: var(--gray-100);
}

/* 图片分享弹窗 */
.share-overlay {
  position: fixed;
  inset: 0;
  padding: var(--space-5);
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
  box-sizing: border-box;
}

.share-modal {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  max-width: 90vw;
  max-height: 90vh;
}

.share-tip {
  margin: 0;
  font-size: var(--text-sm);
  color: #ffffff;
}

.share-image {
  max-width: 100%;
  max-height: 70vh;
  border-radius: var(--radius-md);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
}

.share-close-btn {
  padding: 10px var(--space-8);
  background: #ffffff;
  color: var(--text-primary);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
}

/* 桌面端 */
.report-container.is-desktop {
  max-width: 1200px;
  padding: 0 0 var(--space-12);
}

.report-container.is-desktop .report-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
  align-items: stretch;
}

.report-container.is-desktop .score-card {
  grid-column: 1 / -1;
  padding: var(--space-10) var(--space-5);
}

.report-container.is-desktop .report-col {
  gap: var(--space-5);
}

.report-container.is-desktop .sw-wrapper {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.report-container.is-desktop .report-col:last-child > .card-dark {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  min-height: 280px;
  max-height: 480px;
}

.report-container.is-desktop .chart-container {
  height: 280px;
}

.report-container.is-desktop .report-header {
  padding: var(--space-4) 0 var(--space-6);
}

.report-container.is-desktop .header-title {
  font-size: var(--text-xl);
}
</style>