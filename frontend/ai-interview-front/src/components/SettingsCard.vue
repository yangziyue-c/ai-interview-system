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

      <nav class="settings-nav">
        <button
          v-for="item in items"
          :key="item.key"
          class="settings-item"
          @click="handleItemClick(item)"
        >
          <span class="item-icon-wrap">
            <AppIcon :name="item.icon" :size="20" />
          </span>
          <span class="item-body">
            <span class="item-label">{{ item.label }}</span>
            <span class="item-desc">{{ item.desc }}</span>
          </span>
          <AppIcon name="chevron-right" :size="16" class="item-arrow" />
        </button>
      </nav>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { showToast } from '@/utils/toast'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 卡片遮罩相对父容器的上下偏移
  // MainLayout 传 56px/72px 避开顶栏和 tab 栏；LauncherPage 传默认值覆盖全容器
  offsetTop: { type: String, default: '0' },
  offsetBottom: { type: String, default: '0' }
})

const emit = defineEmits(['update:modelValue'])

// 分类列表
const items = [
  { key: 'account',      icon: 'user',    label: '账户',        desc: '个人信息与登录' },
  { key: 'notification', icon: 'bell',    label: '通知',        desc: '消息提醒与推送' },
  { key: 'voice',        icon: 'mic',     label: '语音与音频',  desc: '麦克风与语音识别' },
  { key: 'appearance',   icon: 'palette', label: '外观',        desc: '主题与显示' },
  { key: 'privacy',      icon: 'shield',  label: '数据与隐私',  desc: '隐私与安全' },
  { key: 'about',        icon: 'info',    label: '关于',        desc: '版本与信息' }
]

const handleClose = () => {
  emit('update:modelValue', false)
}

// 分类点击：对应面板待产品规划，暂时给出中性提示
const handleItemClick = (item) => {
  showToast(`「${item.label}」暂未开放`)
}

const handleEsc = (e) => {
  if (e.key === 'Escape' && props.modelValue) {
    handleClose()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleEsc)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleEsc)
})
</script>

<style scoped>
/* 遮罩：绝对定位在父容器内
   上下偏移由父组件传入（MainLayout 避开顶栏和 tab 栏） */
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

/* 卡片：用 box-shadow 做 1px 描边，避免 border 在圆角处露出浅色 */
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

/* 头部：深色，与主体白色形成对比 */
.settings-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-5);
  background: var(--gray-900);
  /* 顶部圆角与卡片外框对齐，避免圆角处露白 */
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

/* 分类列表 */
.settings-nav {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.settings-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  text-align: left;
  cursor: pointer;
  font-family: inherit;
  transition: background var(--duration-fast) var(--ease-out);
}

.settings-item:hover {
  background: var(--gray-50);
}

.settings-item:active {
  background: var(--gray-100);
}

.item-icon-wrap {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gray-100);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  flex-shrink: 0;
  transition: background var(--duration-fast) var(--ease-out);
}

.settings-item:hover .item-icon-wrap {
  background: var(--gray-200);
}

.item-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.item-label {
  font-size: var(--text-base);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.item-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.item-arrow {
  color: var(--text-disabled);
  flex-shrink: 0;
  transition: color var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}

.settings-item:hover .item-arrow {
  color: var(--text-primary);
  transform: translateX(2px);
}
</style>