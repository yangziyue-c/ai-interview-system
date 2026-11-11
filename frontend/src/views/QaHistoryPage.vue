<template>
  <div class="qa-history-container" :class="{ 'is-desktop': isDesktop }">
    <div class="page-header">
      <button class="back-btn" @click="goBack">
        <AppIcon name="chevron-left" :size="18" />
        <span>返回</span>
      </button>

      <div class="header-center">
        <span class="page-title">{{ positionName }}</span>
        <span class="page-subtitle">{{ formatDate(createdAt) }}</span>
      </div>

      <div class="header-right">
        <span class="round-info">{{ qaList.length }} 题</span>
        <button
          v-if="!loading && qaList.length > 0"
          class="copy-btn"
          @click="copyAll"
          aria-label="复制全文"
        >
          <AppIcon name="copy" :size="16" />
        </button>
      </div>
    </div>

    <div class="qa-list dark-scrollbar" ref="qaListRef">
      <div v-if="loading" class="empty-state">
        <AppIcon name="loading" :size="28" class="spin" />
        <p class="empty-title">加载中...</p>
      </div>

      <div v-else-if="error" class="empty-state">
        <AppIcon name="alert" :size="32" class="empty-icon" />
        <p class="empty-title">加载失败</p>
        <span class="empty-hint">请检查网络后重试</span>
      </div>

      <div v-else-if="qaList.length === 0" class="empty-state">
        <AppIcon name="file" :size="32" class="empty-icon" />
        <p class="empty-title">暂无问答记录</p>
      </div>

      <div v-else v-for="(qa, idx) in qaList" :key="idx" class="qa-pair">
        <div class="round-divider">
          <span class="round-line"></span>
          <span class="round-badge">第 {{ qa.round }} 题</span>
          <span class="round-line"></span>
        </div>

        <div class="message assistant">
          <div class="avatar avatar-ai">
            <AppIcon name="audio-lines" :size="18" />
          </div>
          <div class="bubble-wrapper">
            <div class="bubble ai-bubble">{{ qa.question }}</div>
            <div class="qa-tools">
              <span
                v-if="qa.needs_improvement === true"
                class="qa-tag-warn"
              >
                待提升
              </span>
              <button class="sample-btn" @click="openSampleAnswer(qa)">
                <AppIcon name="lightbulb" :size="12" />
                <span>示范作答</span>
              </button>
            </div>
          </div>
        </div>

        <template v-if="(qa.engine_turns || []).length">
          <template v-for="(t, ti) in qa.engine_turns" :key="ti">
            <div v-if="t.answer" class="message user">
              <div class="bubble user-bubble">{{ t.answer }}</div>
              <div class="avatar avatar-user">
                <AppIcon name="user" :size="18" />
              </div>
            </div>
            <div v-if="t.reply" class="message assistant">
              <div class="avatar avatar-ai">
                <AppIcon name="audio-lines" :size="18" />
              </div>
              <div class="bubble ai-bubble">{{ t.reply }}</div>
            </div>
          </template>
        </template>

        <div v-else class="message user">
          <div
            class="bubble user-bubble"
            :class="{ 'bubble-empty': !qa.answer }"
          >
            {{ qa.answer || '（未作答）' }}
          </div>
          <div class="avatar avatar-user">
            <AppIcon name="user" :size="18" />
          </div>
        </div>
      </div>
    </div>

    <div class="footer-bar">
      <button class="back-report-btn" @click="goBack">返回报告</button>
    </div>

    <!-- 示范作答弹窗 -->
    <div
      v-if="sampleAnswerVisible"
      class="sample-overlay"
      @click.self="closeSampleAnswer"
    >
      <div class="sample-dialog">
        <header class="sample-header">
          <div class="sample-title-row">
            <AppIcon name="lightbulb" :size="16" />
            <h3 class="sample-title">示范作答</h3>
          </div>
          <button class="sample-close" @click="closeSampleAnswer" aria-label="关闭">
            <AppIcon name="close" :size="18" />
          </button>
        </header>

        <div v-if="currentSampleQa" class="sample-question">
          <span class="sample-q-label">第 {{ currentSampleQa.round }} 题</span>
          <p class="sample-q-text">{{ currentSampleQa.question }}</p>
        </div>

        <div class="sample-body dark-scrollbar">
          <div v-if="sampleAnswerLoading" class="sample-loading">
            <AppIcon name="loading" :size="20" class="spin" />
            <span>正在生成示范作答，首次需要数秒...</span>
          </div>

          <div v-else-if="sampleAnswerError" class="sample-error">
            <AppIcon name="info" :size="16" />
            <span>{{ sampleAnswerError }}</span>
          </div>

          <div v-else-if="sampleAnswerData" class="sample-content">
            {{ sampleAnswerData.content }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMediaQuery } from '@/utils/useMediaQuery'
import AppIcon from '@/components/AppIcon.vue'
import { getInterviewDetail } from '@/api/interview'
import { getPositions, getPositionName } from '@/api/position'
import { getSampleAnswer } from '@/api/report'
import { showToast } from '@/utils/toast'

const router = useRouter()
const route = useRoute()

const isDesktop = useMediaQuery('(min-width: 1024px)')

const loading = ref(true)
const error = ref(false)
const qaList = ref([])
const position = ref('')
const positionName = ref('未命名岗位')
const createdAt = ref('')
const qaListRef = ref(null)
const interviewId = ref(null)

// 示范作答状态
const sampleAnswerVisible = ref(false)
const sampleAnswerLoading = ref(false)
const sampleAnswerData = ref(null)
const sampleAnswerError = ref('')
const currentSampleQa = ref(null)

const formatDate = (val) => {
  if (!val) return ''
  const d = new Date(val)
  if (isNaN(d.getTime())) return val
  return d.toLocaleDateString('zh-CN')
}

const goBack = () => {
  const recordId = route.query.recordId
  if (!recordId) {
    router.push('/main/interview')
    return
  }
  router.push({
    path: '/main/report',
    query: {
      recordId,
      fromHistory: route.query.fromHistory || 'false'
    }
  })
}

const openSampleAnswer = async (qa) => {
  // 优先使用后端返回的 id
  const qaId = qa.id || qa.qa_id
  if (!interviewId.value || !qaId) {
    showToast('该题暂不支持生成示范作答')
    return
  }

  currentSampleQa.value = qa
  sampleAnswerVisible.value = true
  sampleAnswerLoading.value = true
  sampleAnswerData.value = null
  sampleAnswerError.value = ''

  try {
    const data = await getSampleAnswer(interviewId.value, qaId)
    if (!data || data.available === false) {
      sampleAnswerError.value = data?.notice || '这道题暂无示范作答'
    } else {
      sampleAnswerData.value = data
    }
  } catch (e) {
    sampleAnswerError.value = e.message || '生成失败，请稍后再试'
  } finally {
    sampleAnswerLoading.value = false
  }
}

const closeSampleAnswer = () => {
  sampleAnswerVisible.value = false
  setTimeout(() => {
    sampleAnswerData.value = null
    sampleAnswerError.value = ''
    currentSampleQa.value = null
  }, 200)
}

const buildFullText = () => {
  const lines = []

  lines.push(`AI 模拟面试 - ${positionName.value}`)
  if (createdAt.value) {
    lines.push(formatDate(createdAt.value))
  }
  lines.push('')

  qaList.value.forEach(qa => {
    lines.push(`第 ${qa.round} 题`)
    lines.push(`AI：${qa.question || ''}`)

    const turns = qa.engine_turns || []
    if (turns.length) {
      turns.forEach(t => {
        if (t.answer) lines.push(`我：${t.answer}`)
        if (t.reply) lines.push(`AI：${t.reply}`)
      })
    } else {
      lines.push(`我：${qa.answer || '（未作答）'}`)
    }

    lines.push('')
  })

  return lines.join('\n').trim()
}

const copyAll = async () => {
  const text = buildFullText()
  if (!text) {
    showToast('暂无可复制的内容')
    return
  }

  let copied = false

  try {
    await navigator.clipboard.writeText(text)
    copied = true
  } catch (e) {
    const textarea = document.createElement('textarea')
    textarea.value = text
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
    showToast('已复制到剪贴板')
  } else {
    showToast('复制失败，请手动选择复制')
  }
}

onMounted(async () => {
  const recordId = route.query.recordId
  if (!recordId) {
    console.warn('缺少 recordId')
    loading.value = false
    return
  }

  try {
    await getPositions()
  } catch (e) {
    console.warn('加载岗位列表失败', e)
  }

  try {
    const data = await getInterviewDetail(recordId)
    qaList.value = data.qa_records || []
    position.value = data.position || ''
    positionName.value = getPositionName(data.position) || '未命名岗位'
    createdAt.value = data.created_at || ''
    interviewId.value = data.id
  } catch (e) {
    console.error('加载问答记录失败', e)
    error.value = true
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* 容器 */
.qa-history-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 64px);
  max-height: 700px;
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
  font-family: var(--font-sans);
}

/* 顶部信息栏 */
.page-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-default);
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
  flex-shrink: 0;
  transition: color var(--duration-fast) var(--ease-out),
              background var(--duration-fast) var(--ease-out);
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.page-subtitle {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.round-info {
  padding: 3px var(--space-3);
  background: var(--gray-100);
  color: var(--text-primary);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  border-radius: var(--radius-full);
}

.copy-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out);
}

.copy-btn:hover {
  background: var(--gray-50);
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.copy-btn:active {
  transform: scale(0.94);
}

/* 问答列表 */
.qa-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  background: var(--gray-50);
}

.qa-pair {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.round-divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-1);
}

.round-line {
  flex: 1;
  height: 1px;
  background: var(--border-default);
}

.round-badge {
  padding: 2px var(--space-3);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  white-space: nowrap;
}

/* 消息气泡 */
.message {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  max-width: 85%;
}

.message.user {
  align-self: flex-end;
  flex-direction: row;
}

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-default);
}

.avatar-ai {
  background: var(--bg-card);
  color: var(--text-primary);
}

.avatar-user {
  background: var(--gray-900);
  color: var(--text-invert);
  border-color: var(--gray-900);
}

.bubble-wrapper {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.bubble {
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  word-break: break-word;
  border-radius: var(--radius-lg);
}

.ai-bubble {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
  border-top-left-radius: var(--radius-sm);
}

.user-bubble {
  background: var(--gray-900);
  color: var(--text-invert);
  border-top-right-radius: var(--radius-sm);
}

.user-bubble.bubble-empty {
  background: var(--gray-500);
  color: var(--gray-100);
  font-style: italic;
}

/* 工具条 */
.qa-tools {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 2px;
}

.qa-tag-warn {
  padding: 1px var(--space-2);
  background: var(--warning-bg);
  color: var(--warning);
  font-size: 10px;
  font-weight: var(--font-semibold);
  border-radius: var(--radius-full);
}

.sample-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-2);
  background: transparent;
  color: var(--text-tertiary);
  border: none;
  font-size: 11px;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out);
}

.sample-btn:hover {
  color: var(--text-primary);
  text-decoration: underline;
}

/* 空状态 */
.empty-state {
  padding: var(--space-12) var(--space-5);
  text-align: center;
}

.empty-icon {
  color: var(--text-disabled);
}

.empty-title {
  margin: var(--space-3) 0 0 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.empty-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.spin {
  color: var(--text-tertiary);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 底部按钮 */
.footer-bar {
  flex-shrink: 0;
  padding: var(--space-3) var(--space-4) calc(var(--space-3) + env(safe-area-inset-bottom));
  background: var(--bg-card);
  border-top: 1px solid var(--border-default);
}

.back-report-btn {
  width: 100%;
  padding: 11px var(--space-4);
  background: var(--gray-900);
  color: var(--text-invert);
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.back-report-btn:hover {
  background: var(--gray-800);
}

/* 示范作答弹窗 */
.sample-overlay {
  position: fixed;
  inset: 0;
  padding: var(--space-5);
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  box-sizing: border-box;
  animation: fadeIn 0.2s var(--ease-out);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.sample-dialog {
  width: 100%;
  max-width: 560px;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-xl);
  animation: scaleIn 0.25s var(--ease-out);
}

@keyframes scaleIn {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}

.sample-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  background: var(--gray-900);
  color: var(--gray-50);
}

.sample-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--gray-50);
}

.sample-title {
  margin: 0;
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--gray-50);
}

.sample-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--gray-400);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.sample-close:hover {
  background: var(--gray-800);
  color: var(--gray-50);
}

.sample-question {
  flex-shrink: 0;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border-subtle);
  background: var(--gray-50);
}

.sample-q-label {
  display: inline-block;
  padding: 1px var(--space-2);
  background: var(--gray-200);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: var(--font-semibold);
  border-radius: var(--radius-full);
  margin-bottom: var(--space-2);
}

.sample-q-text {
  margin: 0;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-primary);
  font-weight: var(--font-medium);
}

.sample-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5);
  min-height: 120px;
}

.sample-loading,
.sample-error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-5) 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  justify-content: center;
}

.sample-error {
  color: var(--text-secondary);
  justify-content: flex-start;
}

.sample-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-primary);
}

/* 桌面端 */
.qa-history-container.is-desktop {
  height: 100%;
  max-height: none;
  border-radius: 0;
  border: none;
}

.qa-history-container.is-desktop .message {
  max-width: 65%;
}

.qa-history-container.is-desktop .qa-list {
  padding: var(--space-6) var(--space-8);
  gap: var(--space-6);
}

.qa-history-container.is-desktop .footer-bar {
  padding: var(--space-4) var(--space-8);
}

.qa-history-container.is-desktop .back-report-btn {
  max-width: 400px;
  margin: 0 auto;
  display: block;
}
</style>