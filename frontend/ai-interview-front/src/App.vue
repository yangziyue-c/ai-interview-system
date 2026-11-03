<template>
  <div v-if="hasError" class="error-fallback">
    <div class="error-card">
      <h2 class="error-title">页面出现异常</h2>
      <p class="error-desc">{{ errorMessage }}</p>
      <div class="error-actions">
        <button class="error-btn" @click="reload">刷新页面</button>
      </div>
    </div>
  </div>

  <template v-else>
    <router-view v-slot="{ Component }">
      <transition name="page-fade" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
    <Toast />
    <ConfirmDialog />
  </template>
</template>

<script setup>
import { ref, onErrorCaptured } from 'vue'
import Toast from '@/components/Toast.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const hasError = ref(false)
const errorMessage = ref('')

// 捕获所有子组件抛出的错误
onErrorCaptured((err, instance, info) => {
  console.error('[错误边界捕获]', err, info)
  hasError.value = true
  errorMessage.value = err?.message || '未知错误'
  // 返回 false 阻止错误继续向上传播
  return false
})

const reload = () => {
  window.location.reload()
}
</script>

<style>
/* 错误兜底页面 */
.error-fallback {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: #09090b;
  box-sizing: border-box;
}

.error-card {
  max-width: 400px;
  width: 100%;
  padding: 32px 24px;
  background: #ffffff;
  border-radius: 16px;
  text-align: center;
}

.error-title {
  margin: 0 0 8px 0;
  font-size: 20px;
  font-weight: 700;
  color: #18181b;
}

.error-desc {
  margin: 0 0 24px 0;
  font-size: 14px;
  line-height: 1.5;
  color: #71717a;
  word-break: break-word;
}

.error-actions {
  display: flex;
  gap: 8px;
}

.error-btn {
  flex: 1;
  padding: 11px 16px;
  background: #18181b;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
}

.error-btn:hover {
  background: #27272a;
}

/* 页面切换过渡动画 */
.page-fade-enter-active {
  transition: opacity 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.page-fade-leave-active {
  transition: opacity 0.1s cubic-bezier(0.4, 0, 0.2, 1);
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
}

/* 全局基础样式 */
html,
body {
  margin: 0;
  padding: 0;
  height: 100%;
  overflow: hidden;
  background: var(--gray-950);
}

#app {
  height: 100%;
  background: var(--gray-950);
}

* {
  box-sizing: border-box;
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: transparent;
  border-radius: 4px;
}

::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 4px;
  border: 2px solid transparent;
  background-clip: padding-box;
  transition: background 0.2s ease;
}

::-webkit-scrollbar-thumb:hover {
  background: #a0a0a0;
  background-clip: padding-box;
  border: 2px solid transparent;
}

::-webkit-scrollbar-thumb:active {
  background: #808080;
  background-clip: padding-box;
  border: 2px solid transparent;
}

.dark-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  background-clip: padding-box;
  border: 2px solid transparent;
}

.dark-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.35);
  background-clip: padding-box;
  border: 2px solid transparent;
}

* {
  scrollbar-width: thin;
  scrollbar-color: #d0d0d0 transparent;
}
</style>