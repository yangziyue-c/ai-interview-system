<template>
  <div class="hall-container" :class="{ 'is-desktop': isDesktop }">
    <div class="hall-header">
      <h2 class="hall-title">
        {{ jobList.length > 0 ? '选择你的面试岗位' : '加载中...' }}
      </h2>
      <p class="hall-subtitle">选定方向，开启 AI 模拟面试</p>
    </div>

    <button class="anchor-entry" @click="goAnchor">
      <AppIcon name="sparkles" :size="18" />
      <span class="anchor-entry-text">
        <strong>不确定选哪个岗位？</strong>
        <span>完成 20 条量表，综合兴趣、能力与置信度找到方向</span>
      </span>
      <AppIcon name="chevron-right" :size="18" class="anchor-entry-arrow" />
    </button>

    <div v-if="loading" class="state-card">
      <AppIcon name="loading" :size="28" class="state-icon spin" />
      <p>加载岗位信息中...</p>
    </div>

    <div v-else-if="loadError" class="state-card">
      <AppIcon name="alert" :size="28" class="state-icon" />
      <p>加载失败，请检查网络</p>
      <button class="retry-btn" @click="loadJobs">重试</button>
    </div>

    <div v-else-if="jobList.length > 0" class="card-grid">
      <div
        v-for="(job, index) in jobList"
        :key="job.code"
        class="job-card"
        :style="{ animationDelay: (0.05 + index * 0.05) + 's' }"
        @click="goToDetail(job)"
      >
        <div class="card-icon-wrap">
          <AppIcon :name="getJobIconName(job.code)" :size="24" />
        </div>

        <div class="card-body">
          <h3 class="card-title">{{ job.name }}</h3>
          <p class="card-tech">{{ (job.tech_stack || []).join('、') }}</p>
        </div>

        <div class="card-action">
          <AppIcon name="chevron-right" :size="18" />
        </div>
      </div>
    </div>

    <div v-else class="state-card">
      <AppIcon name="info" :size="28" class="state-icon" />
      <p>暂无岗位信息，请联系管理员</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getJobIconName } from '@/config/jobIcons'
import { getPositions } from '@/api/position'

const router = useRouter()
const jobList = ref([])
const loading = ref(true)
const loadError = ref(false)

const isDesktop = useMediaQuery('(min-width: 1024px)')

const goAnchor = () => {
  router.push('/main/career-anchor')
}

const goToDetail = (job) => {
  router.push({
    path: '/main/interview/detail',
    query: {
      code: job.code
    }
  })
}

const loadJobs = async () => {
  loading.value = true
  loadError.value = false
  try {
    jobList.value = await getPositions()
  } catch (error) {
    console.error('加载岗位数据失败:', error)
    jobList.value = []
    loadError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadJobs()
})
</script>

<style scoped>
/* 容器 */
.hall-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

/* 页面标题 */
.hall-header {
  padding: var(--space-3) 0 var(--space-5);
  animation: fadeInUp 0.35s var(--ease-out);
}

/* 岗位倾向速测入口 */
.anchor-entry {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  margin-bottom: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.anchor-entry:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}

.anchor-entry-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.anchor-entry-text strong {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.anchor-entry-text span {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.anchor-entry-arrow {
  flex-shrink: 0;
  color: var(--text-tertiary);
}

.hall-title {
  margin: 0 0 var(--space-2) 0;
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

.hall-subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 加载 / 空 / 错误状态卡片 */
.state-card {
  padding: var(--space-12) var(--space-5);
  text-align: center;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.state-icon {
  color: var(--text-tertiary);
  margin-bottom: var(--space-3);
}

.state-card p {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.retry-btn {
  margin-top: var(--space-4);
  padding: 8px var(--space-5);
  background: var(--gray-900);
  color: var(--text-invert);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.retry-btn:hover {
  background: var(--gray-800);
}

.retry-btn:active {
  transform: scale(0.98);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 岗位卡片列表 */
.card-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.job-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  cursor: pointer;
  opacity: 0;
  animation: fadeInUp 0.35s var(--ease-out) forwards;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.job-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}

.job-card:active {
  background: var(--gray-50);
}

.card-icon-wrap {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  flex-shrink: 0;
  transition: background var(--duration-fast) var(--ease-out);
}

.job-card:hover .card-icon-wrap {
  background: var(--gray-200);
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-title {
  margin: 0 0 var(--space-1) 0;
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.card-tech {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  line-height: var(--leading-normal);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-action {
  color: var(--text-disabled);
  flex-shrink: 0;
  transition: color var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.job-card:hover .card-action {
  color: var(--text-primary);
  transform: translateX(2px);
}

/* 桌面端 */
.hall-container.is-desktop {
  max-width: 1200px;
  padding: 0 0 var(--space-12);
}

.hall-container.is-desktop .hall-header {
  padding: var(--space-4) 0 var(--space-8);
}

.hall-container.is-desktop .hall-title {
  font-size: var(--text-2xl);
}

.hall-container.is-desktop .card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-5);
}

.hall-container.is-desktop .job-card {
  flex-direction: column;
  align-items: flex-start;
  padding: var(--space-6);
  gap: var(--space-4);
}

.hall-container.is-desktop .card-icon-wrap {
  width: 56px;
  height: 56px;
}

.hall-container.is-desktop .card-title {
  font-size: var(--text-lg);
}

.hall-container.is-desktop .card-tech {
  font-size: var(--text-sm);
  white-space: normal;
}

.hall-container.is-desktop .card-action {
  align-self: flex-start;
}
</style>
