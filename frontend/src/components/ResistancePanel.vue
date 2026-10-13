<script setup lang="ts">
import { fmtPct } from '@/lib/ride'

defineProps<{ sim: number; level: number }>()
/** Trainer difficulty 0–1. */
const difficulty = defineModel<number>('difficulty', { required: true })
</script>

<template>
  <div class="resist">
    <div class="k">Odpor do šlapek</div>
    <div class="bars">
      <span v-for="i in 10" :key="i" :class="{ on: i <= level }" :style="{ height: `${23 + i * 7}%` }" />
    </div>
    <div class="row">
      <span
        >úroveň <b class="num">{{ level }}</b
        >/10</span
      >
      <span
        >simulovaný sklon <b class="num">{{ fmtPct(sim) }}</b></span
      >
    </div>
    <input
      type="range"
      min="0"
      max="100"
      step="5"
      aria-label="Obtížnost"
      :value="Math.round(difficulty * 100)"
      @input="difficulty = Number(($event.target as HTMLInputElement).value) / 100"
    />
    <div class="row">
      <span>obtížnost</span><span class="num">{{ Math.round(difficulty * 100) }} %</span>
    </div>
    <div class="trainer"><span class="dot" />Trenažér nepřipojen</div>
  </div>
</template>

<style scoped>
.resist {
  padding: 12px 14px;
  width: 250px;
}
.bars {
  display: flex;
  gap: 3px;
  margin: 8px 0 6px;
  height: 34px;
  align-items: flex-end;
}
.bars span {
  flex: 1;
  border-radius: 2px;
  background: var(--line);
}
.bars span.on {
  background: var(--accent);
}
.row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-2);
}
input {
  width: 100%;
  margin: 8px 0 2px;
  accent-color: var(--accent);
}
.trainer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
}
@media (max-width: 760px) {
  .resist {
    width: 190px;
  }
}
</style>
