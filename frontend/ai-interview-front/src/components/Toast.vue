<template>
  <transition name="toast-fade">
    <div v-if="toastState.visible" class="toast">
      {{ toastState.text }}
    </div>
  </transition>
</template>

<script setup>
import { toastState } from '@/utils/toast'
</script>

<style scoped>
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  padding: var(--space-3) var(--space-5);
  background: var(--gray-900);
  color: var(--text-invert);
  font-size: var(--text-sm);
  border-radius: var(--radius-full);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--gray-700);
  z-index: 99999;
  pointer-events: none;
  max-width: 80vw;
  text-align: center;
  word-break: break-word;
}

.toast-fade-enter-active {
  transition: opacity 0.25s var(--ease-out),
              transform 0.25s var(--ease-out);
}

.toast-fade-leave-active {
  transition: opacity 0.2s var(--ease-out),
              transform 0.2s var(--ease-out);
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(12px);
}
</style>