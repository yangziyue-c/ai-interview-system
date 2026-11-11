<template>
  <div v-if="modelValue" class="settings-overlay" @click.self="handleClose">
    <div class="settings-card" role="dialog" aria-label="设置">
      <header class="settings-header">
        <div class="settings-header-left">
          <AppIcon name="settings" :size="18" />
          <h3 class="settings-title">设置</h3>
        </div>
        <button class="settings-close" @click="handleClose" aria-label="关闭">
          <AppIcon name="close" :size="18" />
        </button>
      </header>

      <div class="settings-body dark-scrollbar">
        <div v-if="loading" class="settings-state">
          <AppIcon name="loading" :size="20" class="spin" />
          <span>加载中...</span>
        </div>

        <template v-else>
          <section class="settings-group">
            <h4 class="group-title">
              <AppIcon name="briefcase" :size="18" />
              <span>面试偏好</span>
            </h4>

            <div class="setting-row">
              <div class="setting-label">
                <span class="label-text">默认面试岗位</span>
                <span class="label-desc">开始模拟面试时默认选中的岗位</span>
              </div>
              <select
                class="select"
                :value="settings.default_position"
                :disabled="saving"
                @change="handleChange('default_position', $event.target.value)"
              >
                <option value="">未设置</option>
                <option v-for="p in positions" :key="p.code" :value="p.code">
                  {{ p.name }}
                </option>
              </select>
            </div>

            <div class="setting-row">
              <div class="setting-label">
                <span class="label-text">语音作答</span>
                <span class="label-desc">关闭后只能文字作答，录音按钮不可用</span>
              </div>
              <button
                class="switch"
                :class="{ on: settings.voice_answer }"
                :disabled="saving"
                :aria-pressed="settings.voice_answer"
                @click="handleChange('voice_answer', !settings.voice_answer)"
              >
                <span class="switch-thumb"></span>
              </button>
            </div>

            <div class="setting-row">
              <div class="setting-label">
                <span class="label-text">面试官自动朗读</span>
                <span class="label-desc">关闭后面试官消息不会自动朗读</span>
              </div>
              <button
                class="switch"
                :class="{ on: settings.auto_tts }"
                :disabled="saving"
                :aria-pressed="settings.auto_tts"
                @click="handleChange('auto_tts', !settings.auto_tts)"
              >
                <span class="switch-thumb"></span>
              </button>
            </div>

            <div class="setting-row">
              <div class="setting-label">
                <span class="label-text">摄像头体态分析</span>
                <span class="label-desc">关闭后不启动摄像头与关键点采集</span>
              </div>
              <button
                class="switch"
                :class="{ on: settings.body_language }"
                :disabled="saving"
                :aria-pressed="settings.body_language"
                @click="handleChange('body_language', !settings.body_language)"
              >
                <span class="switch-thumb"></span>
              </button>
            </div>
          </section>

          <section class="settings-group">
            <h4 class="group-title">
              <AppIcon name="file" :size="18" />
              <span>报告偏好</span>
            </h4>

            <div class="setting-row">
              <div class="setting-label">
                <span class="label-text">报告展示方式</span>
                <span class="label-desc">报告展示偏好将在后续版本生效</span>
              </div>
              <div class="segmented">
                <button
                  class="seg-item"
                  :class="{ active: settings.report_preference === 'detailed' }"
                  :disabled="saving"
                  @click="handleChange('report_preference', 'detailed')"
                >详细</button>
                <button
                  class="seg-item"
                  :class="{ active: settings.report_preference === 'concise' }"
                  :disabled="saving"
                  @click="handleChange('report_preference', 'concise')"
                >简洁</button>
              </div>
            </div>
          </section>

          <section class="settings-group">
            <h4 class="group-title">
              <AppIcon name="palette" :size="18" />
              <span>外观</span>
            </h4>

            <div class="setting-row">
              <div class="setting-label">
                <span class="label-text">界面主题</span>
                <span class="label-desc">主题切换将在后续版本生效</span>
              </div>
              <div class="segmented">
                <button
                  class="seg-item"
                  :class="{ active: settings.theme === 'light' }"
                  :disabled="saving"
                  @click="handleChange('theme', 'light')"
                >浅色</button>
                <button
                  class="seg-item"
                  :class="{ active: settings.theme === 'dark' }"
                  :disabled="saving"
                  @click="handleChange('theme', 'dark')"
                >深色</button>
                <button
                  class="seg-item"
                  :class="{ active: settings.theme === 'system' }"
                  :disabled="saving"
                  @click="handleChange('theme', 'system')"
                >跟随系统</button>
              </div>
            </div>
          </section>

          <div class="settings-footnote">
            偏好已自动保存，切换后立即生效
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { showToast } from '@/utils/toast'
import { getSettings, updateSettings } from '@/api/settings'
import { getPositions } from '@/api/position'
import { updateMe } from '@/api/auth'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  offsetTop: { type: String, default: '0' },
  offsetBottom: { type: String, default: '0' }
})

const emit = defineEmits(['update:modelValue'])

const DEFAULT_SETTINGS = {
  default_position: '',
  voice_answer: true,
  auto_tts: true,
  body_language: true,
  report_preference: 'detailed',
  theme: 'system'
}

const settings = ref({ ...DEFAULT_SETTINGS })
const positions = ref([])
const loading = ref(true)
const saving = ref(false)

const loadAll = async () => {
  loading.value = true
  try {
    const [s, pos] = await Promise.all([
      getSettings(),
      getPositions().catch((e) => {
        console.warn('加载岗位列表失败', e)
        return []
      })
    ])
    settings.value = { ...DEFAULT_SETTINGS, ...(s || {}) }
    positions.value = pos || []
  } catch (e) {
    console.error('加载设置失败', e)
    showToast('加载设置失败')
  } finally {
    loading.value = false
  }
}

const handleChange = async (key, value) => {
  if (saving.value) return
  const prev = settings.value[key]
  if (prev === value) return

  settings.value = { ...settings.value, [key]: value }
  saving.value = true
  try {
    const updated = await updateSettings({ [key]: value })
    settings.value = { ...DEFAULT_SETTINGS, ...(updated || {}) }

    if (key === 'default_position' && value) {
      await updateMe({ target_position: value }).catch(e => console.warn('同步目标岗位失败', e))
    }
  } catch (e) {
    console.error('保存设置失败', e)
    settings.value = { ...settings.value, [key]: prev }
    showToast(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const handleClose = () => {
  if (saving.value) return
  emit('update:modelValue', false)
}

const handleEsc = (e) => {
  if (e.key === 'Escape' && props.modelValue) {
    handleClose()
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) loadAll()
  }
)

onMounted(() => {
  window.addEventListener('keydown', handleEsc)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleEsc)
})
</script>

<style scoped>
.settings-overlay {
  position: absolute;
  top: v-bind(offsetTop);
  bottom: v-bind(offsetBottom);
  left: 0;
  right: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  animation: settingsFadeIn 0.2s var(--ease-out);
}

@keyframes settingsFadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.settings-card {
  width: 100%;
  max-width: 560px;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: 0 0 0 1px var(--border-default);
  animation: settingsScaleIn 0.2s var(--ease-out);
}

@keyframes settingsScaleIn {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}

.settings-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-5);
  background: var(--gray-900);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}

.settings-header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--gray-50);
}

.settings-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--gray-50);
  letter-spacing: var(--tracking-tight);
}

.settings-close {
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

.settings-close:hover {
  background: var(--gray-800);
  color: var(--gray-50);
}

.settings-close:active {
  transform: scale(0.94);
}

.settings-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5) var(--space-6) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.settings-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-10) 0;
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.settings-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-base);
  font-weight: var(--font-bold);
  color: var(--text-primary);
}

.group-title :deep(.app-icon) {
  color: var(--text-secondary);
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--border-subtle);
}

.setting-row:first-of-type {
  border-top: none;
  padding-top: var(--space-1);
}

.setting-label {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.label-text {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--text-primary);
}

.label-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: var(--leading-normal);
}

.select {
  flex-shrink: 0;
  min-width: 160px;
  padding: 8px 36px 8px var(--space-3);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--bg-card);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%2352525b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  outline: none;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}

.select:focus {
  border-color: var(--gray-900);
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.06);
}

.select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.switch {
  position: relative;
  flex-shrink: 0;
  width: 40px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: var(--radius-full);
  background: var(--gray-300);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}

.switch:hover:not(:disabled) {
  background: var(--gray-400);
}

.switch.on {
  background: var(--gray-900);
}

.switch.on:hover:not(:disabled) {
  background: var(--gray-800);
}

.switch:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.switch-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  background: #ffffff;
  border-radius: var(--radius-full);
  box-shadow: var(--shadow-xs);
  transition: transform var(--duration-fast) var(--ease-out);
}

.switch.on .switch-thumb {
  transform: translateX(16px);
}

.segmented {
  flex-shrink: 0;
  display: inline-flex;
  padding: 2px;
  background: var(--gray-100);
  border-radius: var(--radius-md);
  gap: 2px;
}

.seg-item {
  padding: 6px var(--space-3);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--duration-fast) var(--ease-out),
              color var(--duration-fast) var(--ease-out);
}

.seg-item:hover:not(:disabled):not(.active) {
  color: var(--text-primary);
}

.seg-item.active {
  background: var(--gray-900);
  color: var(--text-invert);
  font-weight: var(--font-semibold);
}

.seg-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.settings-footnote {
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-subtle);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  text-align: center;
}
</style>