<template>
  <div class="profile-container" :class="{ 'is-desktop': isDesktop }">
    <div class="user-card" @click="showUserModal = true">
      <div class="avatar">
        <img v-if="userInfo?.avatar_url" :src="currentUserAvatar" class="avatar-img" alt="" />
        <span v-else>{{ userInfo?.nickname?.charAt(0) || '?' }}</span>
      </div>
      <div class="user-details">
        <p class="username">{{ userInfo?.nickname || '未命名用户' }}</p>
        <p class="user-meta">
          <span>学号：{{ userInfo?.student_id || '未填写' }}</span>
          <span class="dot">·</span>
          <span>目标岗位：{{ getPositionName(userInfo?.target_position) }}</span>
        </p>
      </div>
      <AppIcon name="chevron-right" :size="18" class="user-chevron" />
    </div>

    <div v-if="showUserModal" class="modal-overlay" @click.self="showUserModal = false">
      <div class="modal-card">
        <button class="modal-close" @click="showUserModal = false" aria-label="关闭">
          <AppIcon name="close" :size="18" />
        </button>

        <div class="modal-avatar" @click="triggerAvatarUpload">
          <img v-if="userInfo?.avatar_url" :src="currentUserAvatar" class="avatar-img" alt="" />
          <span v-else>{{ userInfo?.nickname?.charAt(0) || '?' }}</span>
          <div class="avatar-mask">
            <AppIcon name="edit" :size="18" />
          </div>
        </div>
        <p class="avatar-hint">点击头像更换</p>

        <h3 class="modal-name">{{ userInfo?.nickname || '未命名用户' }}</h3>

        <div class="modal-info">
          <div class="info-row">
            <span class="info-label">账号</span>
            <span class="info-value">{{ userInfo?.username || '未填写' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">学号</span>
            <span class="info-value">{{ userInfo?.student_id || '未填写' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">目标岗位</span>
            <span class="info-value">{{ getPositionName(userInfo?.target_position) }}</span>
          </div>
        </div>

        <button class="modal-edit-btn" @click="openEditModal">
          <AppIcon name="edit" :size="16" />
          <span>编辑资料</span>
        </button>

        <button class="modal-edit-btn" @click="goResume">
          <AppIcon name="file" :size="16" />
          <span>我的简历</span>
        </button>

        <button class="modal-logout-btn" @click="handleLogout">
          <AppIcon name="logout" :size="16" />
          <span>退出登录</span>
        </button>
      </div>
    </div>

    <div v-if="showEditModal" class="modal-overlay" @click.self="closeEditModal">
      <div class="modal-card">
        <button class="modal-close" @click="closeEditModal" aria-label="关闭">
          <AppIcon name="close" :size="18" />
        </button>

        <h3 class="modal-name">编辑资料</h3>

        <div class="edit-form">
          <div class="form-field">
            <label>昵称 <span class="required">*</span></label>
            <input v-model="editForm.nickname" class="input" placeholder="请输入昵称" />
          </div>
          <div class="form-field">
            <label>学号 <span class="optional">（选填）</span></label>
            <input v-model="editForm.student_id" class="input" placeholder="请输入学号" />
          </div>
          <div class="form-field">
            <label>目标岗位 <span class="required">*</span></label>
            <select v-model="editForm.target_position" class="input select">
              <option v-for="pos in allPositions" :key="pos.code" :value="pos.code">
                {{ pos.name }}
              </option>
            </select>
          </div>
        </div>

        <div class="edit-buttons">
          <button class="btn-cancel" @click="closeEditModal">取消</button>
          <button class="btn-save" @click="handleSaveProfile" :disabled="saving">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showAvatarPreview" class="modal-overlay" @click.self="cancelAvatarPreview">
      <div class="modal-card">
        <button class="modal-close" @click="cancelAvatarPreview" aria-label="关闭">
          <AppIcon name="close" :size="18" />
        </button>

        <h3 class="modal-name">更换头像</h3>

        <div class="preview-wrap">
          <img :src="pendingPreview" class="preview-img" alt="" />
        </div>
        <p class="preview-hint">预览效果</p>

        <button class="reselect-btn" @click="reselectAvatar">
          <AppIcon name="edit" :size="14" />
          <span>重新选择</span>
        </button>

        <div class="edit-buttons">
          <button class="btn-cancel" @click="cancelAvatarPreview">取消</button>
          <button class="btn-save" @click="confirmAvatarUpload" :disabled="uploadingAvatar">
            {{ uploadingAvatar ? '上传中...' : '确认' }}
          </button>
        </div>
      </div>
    </div>

    <input
      ref="avatarInputRef"
      type="file"
      accept="image/*"
      style="display: none"
      @change="handleAvatarChange"
    />

    <div class="career-entry-card" @click="goCareerAnchor">
      <div class="entry-icon">
        <AppIcon name="award" :size="20" />
      </div>
      <div class="entry-content">
        <h4 class="entry-title">职业锚定测试</h4>
        <p class="entry-desc">{{ careerDesc }}</p>
      </div>
      <AppIcon name="chevron-right" :size="16" class="entry-arrow" />
    </div>

    <div class="latest-suggestion" v-if="latestSuggestion">
      <div class="suggestion-header">
        <AppIcon name="lightbulb" :size="16" />
        <span>最新改进建议</span>
      </div>
      <p class="suggestion-text">{{ latestSuggestion }}</p>
    </div>

    <div class="filter-tabs" v-if="allPositions.length > 0">
      <div class="filter-tab" :class="{ active: currentFilter === 'all' }" @click="changeFilter('all')">
        <span>全部</span>
      </div>
      <div v-for="pos in allPositions" :key="pos.code" class="filter-tab" :class="{ active: currentFilter === pos.code }" @click="changeFilter(pos.code)">
        <span>{{ pos.name }}</span>
      </div>
    </div>

    <div class="stats-card">
      <div class="stat-item">
        <span class="stat-value">{{ stats.total }}</span>
        <span class="stat-label">面试总次数</span>
      </div>
      <div class="stat-divider"></div>
      <div class="stat-item">
        <span class="stat-value">{{ stats.avg }}</span>
        <span class="stat-label">平均分</span>
      </div>
      <div class="stat-divider"></div>
      <div class="stat-item">
        <span class="stat-value">{{ stats.max }}</span>
        <span class="stat-label">最高分</span>
      </div>
    </div>

    <div v-if="growthChartData.length > 0" class="growth-card">
      <div class="growth-header">
        <h3 class="growth-title">能力成长曲线</h3>
        <span class="growth-sub">{{ currentFilter === 'all' ? '全部岗位' : getPositionName(currentFilter) }}</span>
      </div>
      <div ref="growthChartRef" class="chart-container"></div>
    </div>

    <div class="history-section">
      <div class="history-header">
        <h3 class="history-title">面试历史</h3>
        <span class="history-count">{{ historyList.length }} 条记录</span>
      </div>

      <div v-if="historyList.length === 0" class="empty-state">
        <AppIcon name="file" :size="32" class="empty-icon" />
        <p class="empty-title">暂无面试记录</p>
        <span class="empty-hint">快去进行一次模拟面试吧</span>
      </div>

      <div v-else class="history-list">
        <div
          v-for="(item, index) in historyList"
          :key="item.id || index"
          class="history-item"
          :class="{ 'is-progress': item.status === 'in_progress' }"
          :style="{ animationDelay: (0.05 + index * 0.05) + 's' }"
          @click="viewReport(item)"
        >
          <div class="item-icon-wrap">
            <AppIcon :name="getJobIconName(item.position)" :size="18" />
          </div>

          <div class="item-info">
            <div class="item-job-row">
              <span class="item-job">{{ getPositionName(item.position) }}</span>
              <span v-if="item.status === 'in_progress'" class="latest-badge badge-progress">进行中</span>
              <span v-else-if="isLatestFinished(index)" class="latest-badge">最新</span>
            </div>
            <span class="item-date">{{ formatDate(item.created_at) }}</span>
          </div>

          <div class="item-right">
            <span v-if="item.status === 'in_progress'" class="item-progress">第 {{ item.current_round }} 题</span>
            <span v-else class="item-score">{{ item.total_score ?? '—' }}</span>
            <AppIcon name="chevron-right" :size="16" class="item-chevron" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getJobIconName } from '@/config/jobIcons'
import { getMe, updateMe, clearMeCache, currentUser as userInfo, currentUserAvatar } from '@/api/auth'
import { getInterviews } from '@/api/interview'
import { getLatestReport, getGrowth } from '@/api/report'
import { getPositions, getPositionName, clearPositionCache } from '@/api/position'
import { getSettings, updateSettings, globalSettings } from '@/api/settings'
import { uploadAvatar } from '@/api/upload'
import { showToast } from '@/utils/toast'
import { confirmDialog } from '@/utils/confirm'

const router = useRouter()
const isDesktop = useMediaQuery('(min-width: 1024px)')

const historyList = ref([])
const latestSuggestion = ref(null)
const allPositions = ref([])

const showUserModal = ref(false)
const showEditModal = ref(false)
const currentFilter = ref('all')

const stats = ref({ total: 0, avg: '—', max: '—' })

const growthChartData = ref([])
const growthChartRef = ref(null)
let growthChart = null

const editForm = ref({
  nickname: '',
  student_id: '',
  target_position: ''
})
const saving = ref(false)

const avatarInputRef = ref(null)
const uploadingAvatar = ref(false)
const showAvatarPreview = ref(false)
const pendingFile = ref(null)
const pendingPreview = ref('')

// 使用后端返回的 career_anchor_result 判断
const careerDone = computed(() => {
  return globalSettings.value.career_anchor_result !== null && globalSettings.value.career_anchor_result !== undefined
})

const careerDesc = computed(() => {
  if (careerDone.value) {
    const result = globalSettings.value.career_anchor_result
    if (result.decision === 'ambiguous') {
      return '上次结果：方向暂不明确，可重新测试'
    }
    return `上次推荐：${result.name}（倾向指数 ${result.index}），可重新测试`
  }
  return '尚未测试，完成测试即可获得最合适的岗位推荐'
})

const goCareerAnchor = () => {
  router.push({
    path: '/main/career-anchor',
    query: { from: 'profile' }
  })
}

const formatDate = (val) => {
  if (!val) return ''
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  return d.toLocaleDateString('zh-CN')
}

const isLatestFinished = (index) => {
  const firstFinishedIndex = historyList.value.findIndex(
    item => item.status !== 'in_progress'
  )
  return index === firstFinishedIndex
}

const calcStats = (list) => {
  const finishedList = list.filter(i => i.status === 'finished' && i.total_score !== null && i.total_score !== undefined)
  if (finishedList.length === 0) {
    stats.value = { total: 0, avg: '—', max: '—' }
    return
  }
  const total = finishedList.length
  const scores = finishedList.map(i => Number(i.total_score))
  const sum = scores.reduce((a, b) => a + b, 0)
  const avg = (sum / total).toFixed(1)
  const max = Math.max(...scores).toFixed(1)
  stats.value = { total, avg, max }
}

const renderChart = () => {
  if (!growthChartRef.value || growthChartData.value.length === 0) return

  const option = {
    animation: true,
    animationDuration: 1000,
    animationEasing: 'cubicOut',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#18181b',
      borderColor: '#18181b',
      textStyle: { color: '#ffffff', fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: '#e4e4e7', type: 'dashed' } },
      formatter: function (params) {
        const p = params[0];
        return `${p.name}<br/>得分：<b>${p.value}</b>`;
      }
    },
    grid: { left: 36, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: growthChartData.value.map(item => item.date),
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
      data: growthChartData.value.map(item => item.score),
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
          yAxis: Math.round(growthChartData.value.reduce((sum, d) => sum + d.score, 0) / growthChartData.value.length)
        }]
      }
    }]
  }

  if (!growthChart) {
    growthChart = echarts.init(growthChartRef.value)
  }
  growthChart.setOption(option)
}

const handleResize = () => growthChart?.resize()
const loadUser = async () => await getMe()

const loadHistory = async () => {
  const options = currentFilter.value === 'all' ? {} : { position: currentFilter.value }
  historyList.value = await getInterviews(options)
  calcStats(historyList.value)
}

const loadGrowth = async () => {
  try {
    const options = currentFilter.value === 'all' ? {} : { position: currentFilter.value }
    const raw = await getGrowth(options)
    growthChartData.value = raw.map(item => ({ date: formatDate(item.finished_at), score: item.total_score }))
  } catch (e) {
    console.error('加载成长曲线失败', e)
    growthChartData.value = []
  }
}

const loadLatest = async () => {
  const data = await getLatestReport()
  if (data && data.suggestions && data.suggestions.length > 0) {
    latestSuggestion.value = data.suggestions[0]
  } else {
    latestSuggestion.value = null
  }
}

const loadPositions = async () => {
  allPositions.value = await getPositions()
}

const changeFilter = async (code) => {
  if (currentFilter.value === code) return
  currentFilter.value = code
  await Promise.all([loadHistory(), loadGrowth()])
}

const viewReport = (item) => {
  if (item.status === 'in_progress') {
    router.push({
      path: '/main/interview/room',
      query: { position: item.position, name: getPositionName(item.position), from: 'profile' }
    })
    return
  }
  router.push({ path: '/main/report', query: { recordId: item.id, fromHistory: 'true' } })
}

const openEditModal = () => {
  editForm.value = {
    nickname: userInfo.value?.nickname || '',
    student_id: userInfo.value?.student_id || '',
    target_position: userInfo.value?.target_position || allPositions.value[0]?.code || ''
  }
  showEditModal.value = true
}

const closeEditModal = () => {
  if (saving.value) return
  showEditModal.value = false
}

const handleSaveProfile = async () => {
  if (!editForm.value.nickname.trim()) {
    showToast('昵称不能为空')
    return
  }
  if (!editForm.value.target_position) {
    showToast('请选择目标岗位')
    return
  }

  saving.value = true
  try {
    await updateMe({
      nickname: editForm.value.nickname.trim(),
      student_id: editForm.value.student_id.trim() || null,
      target_position: editForm.value.target_position
    })
    // 同步更新默认岗位设置
    if (editForm.value.target_position !== globalSettings.value.default_position) {
      await updateSettings({ default_position: editForm.value.target_position }).catch(e => console.warn(e))
    }
    showEditModal.value = false
    showUserModal.value = false
    showToast('资料已更新')
  } catch (e) {
    console.error('保存失败', e)
    showToast(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const goResume = () => { showUserModal.value = false; router.push('/main/resume') }
const triggerAvatarUpload = () => { if (uploadingAvatar.value) return; avatarInputRef.value?.click() }

const handleAvatarChange = (e) => {
  const file = e.target.files?.[0]
  if (!file) return
  if (file.size > 2 * 1024 * 1024) { showToast('图片不能超过 2MB'); e.target.value = ''; return }
  if (!file.type.startsWith('image/')) { showToast('请选择图片文件'); e.target.value = ''; return }
  if (pendingPreview.value) URL.revokeObjectURL(pendingPreview.value)
  pendingFile.value = file
  pendingPreview.value = URL.createObjectURL(file)
  showAvatarPreview.value = true
  e.target.value = ''
}

const reselectAvatar = () => avatarInputRef.value?.click()
const cancelAvatarPreview = () => {
  if (pendingPreview.value) URL.revokeObjectURL(pendingPreview.value)
  pendingFile.value = null
  pendingPreview.value = ''
  showAvatarPreview.value = false
}

const confirmAvatarUpload = async () => {
  if (!pendingFile.value || uploadingAvatar.value) return
  uploadingAvatar.value = true
  try {
    const { url } = await uploadAvatar(pendingFile.value)
    await updateMe({ avatar_url: url })
    showToast('头像已更新')
    cancelAvatarPreview()
  } catch (err) {
    console.error('上传头像失败', err)
    showToast(err.message || '上传失败')
  } finally {
    uploadingAvatar.value = false
  }
}

const handleLogout = async () => {
  const ok = await confirmDialog({
    title: '退出登录', message: '确定要退出当前账号吗？', confirmText: '退出', cancelText: '取消', danger: true
  })
  if (!ok) return
  localStorage.removeItem('token')
  sessionStorage.removeItem('hasChosenModule')
  clearPositionCache()
  clearMeCache()
  router.push('/login')
}

const handleEsc = (e) => {
  if (e.key !== 'Escape') return
  if (showAvatarPreview.value) cancelAvatarPreview()
  else if (showEditModal.value) closeEditModal()
  else if (showUserModal.value) showUserModal.value = false
}

watch([showUserModal, showEditModal, showAvatarPreview], ([a, b, c]) => {
  document.body.style.overflow = (a || b || c) ? 'hidden' : ''
})

watch(() => growthChartData.value, (newVal) => {
  if (newVal.length > 0) {
    nextTick(() => {
      requestAnimationFrame(() => { renderChart() })
    })
  } else {
    if (growthChart) { growthChart.dispose(); growthChart = null }
  }
}, { deep: true })

onMounted(() => {
  window.addEventListener('keydown', handleEsc)
  window.addEventListener('resize', handleResize)
  loadPositions()
  loadUser()
  loadHistory()
  loadLatest()
  getSettings().catch(() => {})
  loadGrowth()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleEsc)
  window.removeEventListener('resize', handleResize)
  document.body.style.overflow = ''
  if (pendingPreview.value) URL.revokeObjectURL(pendingPreview.value)
  if (growthChart) { growthChart.dispose(); growthChart = null }
})
</script>

<style scoped>
.profile-container {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 var(--space-1) var(--space-5);
  font-family: var(--font-sans);
}

.user-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-6) var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out);
  animation: fadeInUp 0.35s var(--ease-out);
}
.user-card:hover { border-color: var(--border-strong); background: var(--gray-50); }

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.avatar {
  width: 56px; height: 56px; border-radius: var(--radius-full);
  background: var(--gray-900); color: var(--text-invert);
  font-size: var(--text-lg); font-weight: var(--font-bold);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; overflow: hidden;
}
.avatar-img { width: 100%; height: 100%; object-fit: cover; }
.user-details { flex: 1; min-width: 0; }
.username { margin: 0 0 var(--space-1) 0; font-size: var(--text-lg); font-weight: var(--font-bold); color: var(--text-primary); letter-spacing: var(--tracking-tight); }
.user-meta { margin: 0; font-size: var(--text-sm); color: var(--text-tertiary); display: flex; flex-wrap: wrap; gap: var(--space-1); }
.dot { color: var(--text-disabled); }
.user-chevron { color: var(--text-disabled); flex-shrink: 0; }

.modal-overlay {
  position: fixed; inset: 0; padding: var(--space-5);
  background: rgba(0, 0, 0, 0.5); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  z-index: 999; box-sizing: border-box; animation: fadeIn 0.2s var(--ease-out);
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-card {
  position: relative; width: 340px; max-width: 100%;
  padding: var(--space-8) var(--space-6) var(--space-6);
  background: var(--gray-200); border-radius: var(--radius-xl);
  text-align: center; box-shadow: var(--shadow-xl);
  animation: scaleIn 0.25s var(--ease-out);
}
@keyframes scaleIn { from { transform: scale(0.96); opacity: 0; } to { transform: scale(1); opacity: 1; } }

.modal-close {
  position: absolute; top: var(--space-3); right: var(--space-3);
  width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
  padding: 0; background: transparent; border: none; border-radius: var(--radius-sm);
  color: var(--text-tertiary); cursor: pointer; transition: background var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out);
}
.modal-close:hover { background: var(--gray-100); color: var(--text-primary); }

.modal-avatar {
  position: relative; width: 72px; height: 72px; margin: 0 auto var(--space-2);
  border-radius: var(--radius-full); background: var(--gray-900); color: var(--text-invert);
  font-size: var(--text-xl); font-weight: var(--font-bold); display: flex; align-items: center; justify-content: center;
  overflow: hidden; cursor: pointer;
}
.modal-avatar:hover .avatar-mask { opacity: 1; }
.avatar-mask { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.5); color: #ffffff; display: flex; align-items: center; justify-content: center; opacity: 0; transition: opacity var(--duration-fast) var(--ease-out); }
.avatar-hint { margin: 0 0 var(--space-4) 0; font-size: var(--text-xs); color: var(--text-tertiary); }

.modal-name { margin: 0 0 var(--space-5) 0; font-size: var(--text-lg); font-weight: var(--font-bold); color: var(--text-primary); }

.modal-info {
  padding: var(--space-3) var(--space-4); margin-bottom: var(--space-5);
  background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); text-align: left;
}
.info-row { display: flex; justify-content: space-between; align-items: center; padding: var(--space-2) 0; font-size: var(--text-sm); }
.info-row:not(:last-child) { border-bottom: 1px solid var(--border-subtle); }
.info-label { color: var(--text-tertiary); }
.info-value { color: var(--text-primary); font-weight: var(--font-medium); }

.modal-edit-btn {
  width: 100%; display: flex; align-items: center; justify-content: center; gap: var(--space-2);
  padding: 11px var(--space-4); margin-bottom: var(--space-2); background: var(--bg-card); color: var(--text-primary);
  border: 1px solid var(--border-default); border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: var(--font-semibold);
  cursor: pointer; transition: background var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out);
}
.modal-edit-btn:hover { background: var(--gray-50); border-color: var(--border-strong); }

.modal-logout-btn {
  width: 100%; display: flex; align-items: center; justify-content: center; gap: var(--space-2);
  padding: 11px var(--space-4); background: var(--gray-900); color: var(--text-invert); border: none;
  border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: var(--font-semibold);
  cursor: pointer; transition: background var(--duration-fast) var(--ease-out);
}
.modal-logout-btn:hover { background: var(--gray-800); }
.modal-logout-btn:active { background: var(--gray-950); }

.preview-wrap {
  width: 140px; height: 140px; margin: 0 auto var(--space-3); border-radius: var(--radius-full);
  overflow: hidden; background: var(--gray-100); border: 3px solid var(--gray-200);
  display: flex; align-items: center; justify-content: center;
}
.preview-img { width: 100%; height: 100%; object-fit: cover; }
.preview-hint { margin: 0 0 var(--space-5) 0; font-size: var(--text-xs); color: var(--text-tertiary); }

.reselect-btn {
  width: 100%; display: flex; align-items: center; justify-content: center; gap: var(--space-2);
  padding: 10px var(--space-4); margin-bottom: var(--space-3); background: transparent; color: var(--text-secondary);
  border: 1px dashed var(--border-strong); border-radius: var(--radius-md); font-size: var(--text-sm); font-weight: var(--font-medium);
  cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out), color var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out);
}
.reselect-btn:hover { border-color: var(--gray-900); color: var(--text-primary); background: var(--gray-50); }

.edit-form { display: flex; flex-direction: column; gap: var(--space-4); margin-bottom: var(--space-5); text-align: left; }
.form-field { display: flex; flex-direction: column; gap: var(--space-2); }
.form-field label { font-size: var(--text-sm); font-weight: var(--font-medium); color: var(--text-primary); }
.required { color: var(--danger); font-weight: var(--font-semibold); margin-left: 2px; }
.optional { color: var(--text-disabled); font-weight: var(--font-normal); font-size: var(--text-xs); }

.input {
  width: 100%; padding: 10px var(--space-3); border: 1px solid var(--border-default);
  border-radius: var(--radius-md); font-size: var(--text-base); color: var(--text-primary); background: var(--bg-card);
  outline: none; box-sizing: border-box; transition: border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out);
}
.input::placeholder { color: var(--text-disabled); }
.input:focus { border-color: var(--gray-900); box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.06); }

.select {
  appearance: none; -webkit-appearance: none; -moz-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%2352525b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 12px center;
  padding-right: 36px; cursor: pointer;
}

.edit-buttons { display: flex; gap: var(--space-2); }
.btn-cancel, .btn-save {
  flex: 1; padding: 11px var(--space-4); border-radius: var(--radius-md);
  font-size: var(--text-sm); font-weight: var(--font-semibold); cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out), border-color var(--duration-fast) var(--ease-out);
}
.btn-cancel { background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border-default); }
.btn-cancel:hover { background: var(--gray-50); border-color: var(--border-strong); }
.btn-save { background: var(--gray-900); color: var(--text-invert); border: 1px solid var(--gray-900); }
.btn-save:hover:not(:disabled) { background: var(--gray-800); }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

.career-entry-card {
  margin-top: var(--space-4); display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-4) var(--space-5); background: var(--bg-card); border: 1px solid var(--border-default);
  border-radius: var(--radius-lg); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); animation: fadeInUp 0.35s var(--ease-out);
}
.career-entry-card:hover { border-color: var(--border-strong); background: var(--gray-50); }
.entry-icon { width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; background: var(--gray-100); color: var(--text-primary); border-radius: var(--radius-md); flex-shrink: 0; }
.entry-content { flex: 1; min-width: 0; }
.entry-title { margin: 0 0 2px; font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary); }
.entry-desc { margin: 0; font-size: var(--text-xs); color: var(--text-tertiary); }
.entry-arrow { color: var(--text-disabled); flex-shrink: 0; }

.latest-suggestion { margin-top: var(--space-4); padding: var(--space-5); background: var(--gray-900); color: var(--text-invert); border-radius: var(--radius-lg); animation: fadeInUp 0.35s var(--ease-out); }
.suggestion-header { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); color: var(--gray-400); }
.suggestion-header span { font-size: var(--text-xs); font-weight: var(--font-semibold); letter-spacing: var(--tracking-wide); text-transform: uppercase; }
.suggestion-text { margin: 0; font-size: var(--text-sm); line-height: var(--leading-relaxed); color: var(--gray-100); }

.filter-tabs { display: flex; gap: var(--space-2); margin-top: var(--space-4); margin-bottom: var(--space-3); overflow-x: auto; padding-bottom: var(--space-1); scrollbar-width: none; }
.filter-tabs::-webkit-scrollbar { display: none; }
.filter-tab { flex-shrink: 0; display: inline-flex; align-items: center; padding: var(--space-2) var(--space-3); background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-full); font-size: var(--text-xs); font-weight: var(--font-medium); color: var(--text-secondary); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); user-select: none; white-space: nowrap; }
.filter-tab:hover { border-color: var(--border-strong); color: var(--text-primary); }
.filter-tab.active { background: var(--gray-900); border-color: var(--gray-900); color: var(--text-invert); }

.stats-card {
  display: grid; grid-template-columns: 1fr 1px 1fr 1px 1fr; align-items: center; justify-items: center;
  min-height: 100px; padding: var(--space-4); background: var(--bg-card); border: 1px solid var(--border-default);
  border-radius: var(--radius-lg); margin-bottom: var(--space-4); animation: fadeInUp 0.35s var(--ease-out);
}
.stat-item { display: flex; flex-direction: column; align-items: center; gap: var(--space-1); width: 100%; }
.stat-value { font-size: var(--text-2xl); font-weight: var(--font-bold); color: var(--text-primary); letter-spacing: var(--tracking-tight); line-height: 1.1; }
.stat-label { font-size: var(--text-xs); color: var(--text-tertiary); }
.stat-divider { width: 1px; height: 32px; background: var(--border-default); }

.growth-card { padding: var(--space-5); background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-lg); margin-bottom: var(--space-5); animation: fadeInUp 0.35s var(--ease-out); }
.growth-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: var(--space-2); }
.growth-title { margin: 0; font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary); }
.growth-sub { font-size: var(--text-xs); color: var(--text-tertiary); }
.chart-container { width: 100%; height: 200px; }

.history-section { margin-top: var(--space-2); }
.history-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: var(--space-3); }
.history-title { margin: 0; font-size: var(--text-base); font-weight: var(--font-bold); color: var(--text-primary); }
.history-count { font-size: var(--text-xs); color: var(--text-tertiary); }
.empty-state { padding: var(--space-10) var(--space-5); background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-lg); text-align: center; }
.empty-icon { color: var(--text-disabled); }
.empty-title { margin: var(--space-3) 0 var(--space-1) 0; font-size: var(--text-sm); font-weight: var(--font-medium); color: var(--text-secondary); }
.empty-hint { font-size: var(--text-xs); color: var(--text-tertiary); }
.history-list { display: flex; flex-direction: column; gap: var(--space-2); }
.history-item { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); cursor: pointer; opacity: 0; animation: fadeInUp 0.3s var(--ease-out) forwards; transition: border-color var(--duration-fast) var(--ease-out), background var(--duration-fast) var(--ease-out); }
.history-item:hover { border-color: var(--border-strong); background: var(--gray-50); }
.history-item.is-progress { border-left: 3px solid var(--success); }
.item-icon-wrap { width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; background: var(--gray-100); border-radius: var(--radius-md); color: var(--text-primary); flex-shrink: 0; }
.item-info { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.item-job-row { display: flex; align-items: center; gap: var(--space-2); }
.item-job { font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-date { font-size: var(--text-xs); color: var(--text-tertiary); }
.latest-badge { display: inline-block; padding: 1px var(--space-2); background: var(--gray-900); color: var(--text-invert); font-size: 10px; font-weight: var(--font-semibold); border-radius: var(--radius-full); letter-spacing: 0.3px; flex-shrink: 0; }
.badge-progress { background: var(--success); color: #ffffff; }
.item-right { display: flex; align-items: center; gap: var(--space-2); flex-shrink: 0; }
.item-score { font-size: var(--text-lg); font-weight: var(--font-bold); color: var(--text-primary); }
.item-progress { font-size: var(--text-xs); font-weight: var(--font-semibold); color: var(--success); }
.item-chevron { color: var(--text-disabled); transition: color var(--duration-fast) var(--ease-out), transform var(--duration-fast) var(--ease-out); }
.history-item:hover .item-chevron { color: var(--text-primary); transform: translateX(2px); }

@media (min-width: 1024px) {
  .profile-container { max-width: 1200px; padding: 0 0 var(--space-12); }
  .user-card { padding: var(--space-8) var(--space-6); gap: var(--space-5); }
  .avatar { width: 64px; height: 64px; font-size: var(--text-xl); }
  .username { font-size: var(--text-xl); }
  .career-entry-card { margin-top: var(--space-5); padding: var(--space-5) var(--space-6); }
  .latest-suggestion { margin-top: var(--space-5); padding: var(--space-6); }
  .stats-card { padding: var(--space-6); margin-top: var(--space-5); min-height: 120px; }
  .stat-value { font-size: var(--text-3xl); }
  .growth-card { padding: var(--space-6); margin-bottom: var(--space-6); }
  .chart-container { height: 280px; }
  .history-section { margin-top: var(--space-6); }
}
</style>
