<template>
  <div class="detail-container" :class="{ 'is-desktop': isDesktop }">
    <div class="detail-header">
      <button class="back-btn" @click="goBack">
        <AppIcon name="chevron-left" :size="18" />
        <span>返回</span>
      </button>
    </div>

    <div class="detail-card">
      <div class="detail-icon-wrap">
        <AppIcon
          :name="getJobIconName(jobInfo.code)"
          :size="isDesktop ? 44 : 36"
        />
      </div>

      <h1 class="detail-title">{{ jobInfo.name }}</h1>

      <div class="info-wrapper">
        <div class="info-section">
          <div class="section-label">
            <AppIcon name="layers" :size="16" />
            <span>技术栈要求</span>
          </div>
          <p class="info-text">{{ (jobInfo.tech_stack || []).join('、') }}</p>
        </div>

        <div class="info-section">
          <div class="section-label">
            <AppIcon name="lightbulb" :size="16" />
            <span>考察重点</span>
          </div>
          <p class="info-text">{{ (jobInfo.focus || []).join('、') }}</p>
        </div>
      </div>

      <button class="start-btn" @click="handleStartInterview">
        <span>开始面试</span>
        <AppIcon name="chevron-right" :size="18" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getJobIconName } from '@/config/jobIcons'
import { getPositions, getPositionName } from '@/api/position'
import { checkInProgress } from '@/api/interview'
import { confirmDialog } from '@/utils/confirm'

const router = useRouter()
const route = useRoute()

const isDesktop = useMediaQuery('(min-width: 1024px)')

const jobInfo = ref({
  code: '',
  name: '',
  tech_stack: [],
  focus: []
})

const goBack = () => {
  router.push('/main/interview')
}

// 进入面试室前检查是否有进行中的面试
const handleStartInterview = async () => {
  let inProgress = null
  try {
    inProgress = await checkInProgress()
  } catch (e) {
    console.warn('检查面试状态失败', e)
  }

  if (!inProgress) {
    router.push({
      path: '/main/interview/room',
      query: {
        position: jobInfo.value.code,
        name: jobInfo.value.name
      }
    })
    return
  }

  const samePosition = inProgress.position === jobInfo.value.code

  if (samePosition) {
    router.push({
      path: '/main/interview/room',
      query: {
        position: jobInfo.value.code,
        name: jobInfo.value.name
      }
    })
    return
  }

  const inProgressName = getPositionName(inProgress.position)
  const ok = await confirmDialog({
    title: '有未完成的面试',
    message: `你有一场「${inProgressName}」的面试正在进行中。是否先去完成它？`,
    confirmText: '去继续',
    cancelText: '取消'
  })

  if (ok) {
    router.push({
      path: '/main/interview/room',
      query: {
        position: inProgress.position,
        name: inProgressName,
        from: 'detail-redirect'
      }
    })
  }
}

onMounted(async () => {
  const code = route.query.code
  if (!code) {
    router.replace('/main/interview')
    return
  }

  let list = []
  try {
    list = await getPositions()
  } catch (e) {
    console.error('加载岗位列表失败', e)
    router.replace('/main/interview')
    return
  }

  const found = list.find(p => p.code === code)

  if (!found) {
    router.replace('/main/interview')
    return
  }

  jobInfo.value = found
})
</script>

<style scoped>
/* 容器 */
.detail-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

/* 返回按钮 */
.detail-header {
  padding: var(--space-3) 0;
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
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
}

.back-btn:hover {
  color: var(--text-primary);
  background: var(--gray-100);
}

.back-btn:active {
  background: var(--gray-200);
}

/* 详情卡片 */
.detail-card {
  padding: var(--space-8) var(--space-6) var(--space-6);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  text-align: center;
  animation: fadeInUp 0.35s var(--ease-out);
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.detail-icon-wrap {
  width: 72px;
  height: 72px;
  margin: 0 auto var(--space-4);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
}

.detail-title {
  margin: 0 0 var(--space-6) 0;
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}

/* 信息区块 */
.info-wrapper {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  text-align: left;
  margin-bottom: var(--space-6);
}

.info-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.section-label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-primary);
}

.section-label span {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
}

.info-text {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
  background: var(--gray-50);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

/* 开始面试按钮 */
.start-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 13px var(--space-4);
  background: var(--gray-900);
  color: var(--text-invert);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
  letter-spacing: var(--tracking-wide);
}

.start-btn:hover {
  background: var(--gray-800);
}

.start-btn:active {
  background: var(--gray-950);
}

/* 桌面端 */
.detail-container.is-desktop {
  max-width: 900px;
  padding: 0 0 var(--space-12);
}

.detail-container.is-desktop .detail-header {
  padding: var(--space-4) 0;
}

.detail-container.is-desktop .detail-card {
  padding: var(--space-12) var(--space-10) var(--space-10);
  border-radius: var(--radius-xl);
}

.detail-container.is-desktop .detail-icon-wrap {
  width: 88px;
  height: 88px;
  margin-bottom: var(--space-5);
}

.detail-container.is-desktop .detail-title {
  font-size: var(--text-2xl);
  margin-bottom: var(--space-8);
}

.detail-container.is-desktop .info-wrapper {
  flex-direction: row;
  gap: var(--space-5);
}

.detail-container.is-desktop .info-section {
  flex: 1;
}

.detail-container.is-desktop .info-text {
  padding: var(--space-4) var(--space-5);
  font-size: var(--text-base);
}

.detail-container.is-desktop .start-btn {
  max-width: 400px;
  margin: var(--space-8) auto 0;
  padding: 14px var(--space-5);
  font-size: var(--text-base);
}
</style>