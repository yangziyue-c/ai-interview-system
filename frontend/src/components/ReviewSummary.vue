<template>
  <section v-if="visible" class="card review-card">
    <div class="section-header">
      <AppIcon name="clipboard-check" :size="16" />
      <span class="section-title">考后复盘</span>
    </div>

    <p v-if="review.headline" class="review-headline">{{ review.headline }}</p>

    <div v-if="hasCounts" class="review-stats">
      <div v-if="count('topics_seen') !== null" class="review-stat">
        <strong>{{ count('topics_seen') }}</strong>
        <span>覆盖考点</span>
      </div>
      <div v-if="count('topics_hit') !== null" class="review-stat">
        <strong>{{ count('topics_hit') }}</strong>
        <span>已答到</span>
      </div>
      <div v-if="count('topics_missed') !== null" class="review-stat review-stat-warn">
        <strong>{{ count('topics_missed') }}</strong>
        <span>未答到</span>
      </div>
      <div v-if="count('topics_uncovered') !== null" class="review-stat">
        <strong>{{ count('topics_uncovered') }}</strong>
        <span>未覆盖考点</span>
      </div>
    </div>

    <div v-if="gaps.length" class="review-block">
      <h4 class="review-block-title">薄弱考点</h4>
      <div v-for="(gap, index) in gaps" :key="gap.kp_id || index" class="gap-item">
        <div class="gap-title-row">
          <strong>{{ gap.title || '未命名考点' }}</strong>
          <span v-if="gap.domain" class="gap-domain">{{ gap.domain }}</span>
        </div>
        <p v-if="gap.advice" class="gap-advice">{{ gap.advice }}</p>
      </div>
    </div>

    <div v-if="actions.length" class="review-block">
      <h4 class="review-block-title">下一步行动</h4>
      <ul class="review-list">
        <li v-for="(action, index) in actions" :key="action.kp_id || index">
          {{ actionText(action) }}
        </li>
      </ul>
    </div>

    <div v-if="caveats.length" class="review-caveats">
      <div class="caveat-title">
        <AppIcon name="info" :size="14" />
        <span>说明</span>
      </div>
      <ul class="review-list">
        <li v-for="(item, index) in caveats" :key="index">{{ item }}</li>
      </ul>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  review: {
    type: Object,
    default: null
  }
})

const gaps = computed(() => (
  Array.isArray(props.review?.gaps) ? props.review.gaps : []
))

const actions = computed(() => (
  Array.isArray(props.review?.actions) ? props.review.actions : []
))

const caveats = computed(() => (
  Array.isArray(props.review?.caveats) ? props.review.caveats : []
))

const hasCounts = computed(() => (
  Object.keys(props.review?.counts || {}).length > 0
))

const visible = computed(() => Boolean(
  props.review?.headline ||
  gaps.value.length ||
  actions.value.length ||
  caveats.value.length ||
  hasCounts.value
))

const count = (key) => {
  const value = props.review?.counts?.[key]
  if (value === null || value === undefined || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const actionText = (action) => {
  if (typeof action === 'string') return action
  return action?.text || action?.title || '继续练习相关知识点'
}
</script>

<style scoped>
.review-card {
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
}

.section-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  color: var(--text-primary);
}

.section-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
}

.review-headline {
  margin: 0 0 var(--space-4);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
}

.review-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.review-stat {
  padding: var(--space-3);
  background: var(--gray-50);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  text-align: center;
}

.review-stat strong {
  display: block;
  font-size: var(--text-xl);
  line-height: 1.1;
  color: var(--text-primary);
}

.review-stat span {
  display: block;
  margin-top: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.review-stat-warn strong {
  color: var(--warning);
}

.review-block + .review-block {
  margin-top: var(--space-4);
}

.review-block-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-tertiary);
}

.gap-item {
  padding: var(--space-3) 0;
  border-top: 1px solid var(--border-subtle);
}

.gap-item:first-of-type {
  border-top: none;
  padding-top: 0;
}

.gap-title-row {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.gap-title-row strong {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.gap-domain {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.gap-advice {
  margin: var(--space-1) 0 0;
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
}

.review-list {
  margin: 0;
  padding-left: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.review-list li {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
}

.review-caveats {
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--gray-50);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.caveat-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-tertiary);
}
</style>
