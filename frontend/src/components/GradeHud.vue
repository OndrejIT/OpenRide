<script setup lang="ts">
import { computed, ref } from 'vue'
import { gradeColor, tokenReader } from '@/lib/draw'
import { fmtPct, GRADE_LABEL, gradeKind } from '@/lib/ride'

const props = defineProps<{ grade: number; ahead: { meters: number; grade: number } | null }>()

const el = ref<HTMLElement>()
const kind = computed(() => gradeKind(props.grade))
const color = computed(() =>
  el.value && kind.value !== 'flat' ? gradeColor(tokenReader(el.value), props.grade) : undefined,
)
</script>

<template>
  <div ref="el" class="grade-hud">
    <div class="num value" :style="{ color }">{{ fmtPct(grade) }}</div>
    <div class="lbl">{{ GRADE_LABEL[kind] }}</div>
    <div class="next">
      <template v-if="ahead">dalších {{ Math.round(ahead.meters) }} m: {{ fmtPct(ahead.grade) }}</template>
      <template v-else>cíl</template>
    </div>
  </div>
</template>

<style scoped>
.grade-hud {
  text-align: center;
  padding: 10px 22px;
  min-width: 220px;
}
.value {
  font-size: 56px;
  line-height: 1;
}
.lbl {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.12em;
  margin-top: 4px;
}
.next {
  font-size: 13px;
  color: var(--text-2);
  margin-top: 6px;
}
@media (max-width: 760px) {
  .value {
    font-size: 40px;
  }
}
</style>
