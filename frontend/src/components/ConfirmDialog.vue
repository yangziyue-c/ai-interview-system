<template>
  <transition name="dialog-fade">
    <div v-if="state.visible" class="dialog-overlay" @click.self="onCancel">
      <div class="dialog-card">
        <h3 class="dialog-title">{{ state.title }}</h3>
        <p v-if="state.message" class="dialog-message">{{ state.message }}</p>
        <div class="dialog-buttons">
          <button class="btn btn-cancel" @click="onCancel">{{ state.cancelText }}</button>
          <button
            class="btn"
            :class="state.danger ? 'btn-danger' : 'btn-primary'"
            @click="onConfirm"
          >
            {{ state.confirmText }}
          </button>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { confirmState as state } from '@/utils/confirm'

const onConfirm = () => {
  if (state.resolve) state.resolve(true)
  state.visible = false
  state.resolve = null
}

const onCancel = () => {
  if (state.resolve) state.resolve(false)
  state.visible = false
  state.resolve = null
}

const handleEsc = (e) => {
  if (e.key === 'Escape' && state.visible) {
    onCancel()
  }
}

onMounted(() => window.addEventListener('keydown', handleEsc))
onUnmounted(() => window.removeEventListener('keydown', handleEsc))
</script>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  padding: var(--space-5);
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 99998;
  box-sizing: border-box;
}

.dialog-card {
  width: 340px;
  max-width: 100%;
  padding: var(--space-6);
  background: var(--gray-200);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
  animation: scaleIn 0.25s var(--ease-out);
}

@keyframes scaleIn {
  from { transform: scale(0.96); opacity: 0; }
  to   { transform: scale(1); opacity: 1; }
}

.dialog-title {
  margin: 0 0 var(--space-2) 0;
  font-size: var(--text-lg);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  text-align: center;
}

.dialog-message {
  margin: 0 0 var(--space-5) 0;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
  text-align: center;
}

.dialog-buttons {
  display: flex;
  gap: var(--space-2);
}

.btn {
  flex: 1;
  padding: 11px var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out),
              border-color var(--duration-fast) var(--ease-out);
}

.btn:active { transform: scale(0.98); }

/* 取消按钮：白底，在 gray-200 上跳出来 */
.btn-cancel {
  background: var(--bg-card);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-cancel:hover {
  background: var(--gray-50);
  border-color: var(--border-strong);
}

.btn-primary {
  background: var(--gray-900);
  color: var(--text-invert);
  border: 1px solid var(--gray-900);
}

.btn-primary:hover { background: var(--gray-800); }

.btn-danger {
  background: var(--danger);
  color: #ffffff;
  border: 1px solid var(--danger);
}

.btn-danger:hover { background: var(--danger-hover); }

.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: opacity 0.2s var(--ease-out);
}
.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}
</style>