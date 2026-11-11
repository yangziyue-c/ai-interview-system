<template>
  <div class="hall-container" :class="{ 'is-desktop': isDesktop }">
    <div class="hall-header">
      <h2 class="hall-title">
        {{ jobList.length > 0 ? '选择你的面试岗位' : '加载中...' }}
      </h2>
      <p class="hall-subtitle">选定方向，开启 AI 模拟面试</p>
    </div>

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
        :class="{ 'is-default': job.code === globalSettings.default_position }"
        :style="{ animationDelay: (0.05 + index * 0.05) + 's' }"
        @click="goToDetail(job)"
      >
        <div class="card-icon-wrap">
          <AppIcon :name="getJobIconName(job.code)" :size="24" />
        </div>

        <div class="card-body">
          <div class="card-title-row">
            <h3 class="card-title">{{ job.name }}</h3>
            <span v-if="job.code === globalSettings.default_position" class="default-tag">默认</span>
          </div>
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
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getJobIconName } from '@/config/jobIcons'
import { getPositions } from '@/api/position'
import { getSettings, globalSettings } from '@/api/settings'

const router = useRouter()
const rawPositions = ref([])
const loading = ref(true)
const loadError = ref(false)

const isDesktop = useMediaQuery('(min-width: 1024px)')

const jobList = computed(() => {
  const list = [...rawPositions.value]
  const defaultPos = globalSettings.value.default_position
  if (defaultPos) {
    const idx = list.findIndex(p => p.code === defaultPos)
    if (idx > -1) {
      const item = list.splice(idx, 1)[0]
      list.unshift(item)
    }
  }
  return list
})

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
    const positions = await getPositions()
    rawPositions.value = positions
    loading.value = false
    
    // 后台静默拉取设置以更新默认高亮
    getSettings().catch(e => {
      console.warn('拉取默认设置失败', e)
    })
  } catch (error) {
    console.error('加载岗位数据失败:', error)
    rawPositions.value = []
    loadError.value = true
    loading.value = false
  }
}

onMounted(() => {
  loadJobs()
})
</script>

<style scoped>
.hall-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

.hall-header {
  padding: var(--space-3) 0 var(--space-5);
  animation: fadeInUp 0.35s var(--ease-out);
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

.retry-btn:hover { background: var(--gray-800); }
.retry-btn:active { transform: scale(0.98); }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.card-grid { display: flex; flex-direction: column; gap: var(--space-3); }

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

.job-card:active { background: var(--gray-50); }

.job-card.is-default {
  border-color: var(--gray-900);
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

.job-card:hover .card-icon-wrap { background: var(--gray-200); }
.job-card.is-default .card-icon-wrap { background: var(--gray-200); }

.card-body { flex: 1; min-width: 0; }
.card-title-row { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-1); }
.card-title { margin: 0; font-size: var(--text-base); font-weight: var(--font-semibold); color: var(--text-primary); }

.default-tag {
  padding: 1px var(--space-2);
  background: var(--gray-900);
  color: var(--text-invert);
  font-size: 10px;
  font-weight: var(--font-semibold);
  border-radius: var(--radius-full);
  letter-spacing: 0.3px;
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

@media (min-width: 1024px) {
  .hall-container { max-width: 1200px; padding: 0 0 var(--space-12); }
  .hall-container .hall-header { padding: var(--space-4) 0 var(--space-8); }
  .hall-container .hall-title { font-size: var(--text-2xl); }
  .hall-container .card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: var(--space-5);
  }
  .hall-container .job-card {
    flex-direction: column;
    align-items: flex-start;
    padding: var(--space-6);
    gap: var(--space-4);
  }
  .hall-container .card-icon-wrap { width: 56px; height: 56px; }
  .hall-container .card-title-row { margin-bottom: var(--space-2); }
  .hall-container .card-title { font-size: var(--text-lg); }
  .hall-container .card-tech { font-size: var(--text-sm); white-space: normal; }
  .hall-container .card-action { align-self: flex-start; }
}
</style>