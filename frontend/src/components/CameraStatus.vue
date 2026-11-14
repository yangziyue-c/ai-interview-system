<template>
  <div class="camera-status">
    <div v-if="!analysis" class="state-line">
      <AppIcon name="loading" :size="12" class="spin" />
      <span>正在采样...</span>
    </div>

    <!-- 未检测到人体 -->
    <div v-else-if="!analysis.available" class="state-line state-warn">
      <AppIcon name="alert" :size="12" />
      <span>未检测到人体，请调整画面</span>
    </div>

    <!-- 有姿态但证据不足 -->
    <div v-else-if="analysis.score === null" class="state-line">
      <AppIcon name="loading" :size="12" class="spin" />
      <span>{{ qualityText }}</span>
    </div>

    <!-- 有分数 -->
    <div v-else class="state-line">
      <span class="score-num">{{ analysis.score.toFixed(1) }}</span>
      <span class="score-unit">/ 5.0</span>
      <span class="conf-tag" :class="`conf-${analysis.confidence}`">
        {{ confidenceText }}
      </span>
    </div>

    <!-- feedback 有分时才出现 -->
    <ul v-if="analysis?.feedback?.length" class="feedback-list">
      <li v-for="(item, idx) in analysis.feedback" :key="idx">{{ item }}</li>
    </ul>

    <!-- notes 证据不足或无分时可能才有 -->
    <p v-if="!analysis?.feedback && analysis?.notes" class="notes-text">
      {{ analysis.notes }}
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  analysis: { type: Object, default: null }
})

const qualityText = computed(() => {
  const q = props.analysis?.quality_status
  if (q === 'warming_up') return '采样中，约需 3 秒'
  if (q === 'low_visibility') return '画面覆盖不足'
  if (q === 'no_pose') return '未检测到上半身'
  return '采样中...'
})

const confidenceText = computed(() => {
  const c = props.analysis?.confidence
  if (c === 'high') return '高可信'
  if (c === 'medium') return '中可信'
  if (c === 'low') return '低可信'
  return ''
})
</script>

<style scoped>
.camera-status {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.state-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.state-line.state-warn {
  color: var(--warning);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.score-num {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  line-height: 1;
}

.score-unit {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.conf-tag {
  margin-left: auto;
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  font-size: 10px;
  font-weight: var(--font-medium);
}

.conf-high {
  background: var(--success-bg);
  color: var(--success);
}

.conf-medium {
  background: var(--warning-bg);
  color: var(--warning);
}

.conf-low {
  background: var(--gray-100);
  color: var(--text-tertiary);
}

.feedback-list {
  margin: 0;
  padding-left: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.feedback-list li {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: var(--leading-relaxed);
}

.notes-text {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: var(--leading-relaxed);
}
</style>