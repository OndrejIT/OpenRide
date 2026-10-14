<script setup lang="ts">
import type { RecordSummary } from '@/lib/record'
import { fmtKm, fmtM, fmtTime } from '@/lib/ride'

defineProps<{
  summary: RecordSummary
  /** route reached its end (otherwise the rider stopped early) */
  finished: boolean
  saving: boolean
  savedId: number | null
  error: string | null
}>()
const emit = defineEmits<{ save: []; discard: []; resume: [] }>()

const avg = (v: number | null, unit: string) => (v == null ? '–' : `${Math.round(v)} ${unit}`)
</script>

<template>
  <div class="backdrop" role="dialog" aria-modal="true" aria-labelledby="finish-title">
    <div class="dialog">
      <h2 id="finish-title">{{ savedId ? 'Jízda uložena' : finished ? 'Dojeto!' : 'Ukončit jízdu?' }}</h2>
      <dl>
        <dt>Čas jízdy</dt>
        <dd class="num">{{ fmtTime(summary.durationS) }}</dd>
        <dt>Vzdálenost</dt>
        <dd class="num">{{ fmtKm(summary.distanceM) }}</dd>
        <dt>Stoupání</dt>
        <dd class="num">{{ fmtM(summary.elevGainM) }}</dd>
        <dt>Průměrný výkon</dt>
        <dd class="num">{{ avg(summary.avgPower, 'W') }}</dd>
        <dt>Průměrná kadence</dt>
        <dd class="num">{{ avg(summary.avgRpm, 'rpm') }}</dd>
        <dt>Průměrný tep</dt>
        <dd class="num">{{ avg(summary.avgPulse, 'bpm') }}</dd>
      </dl>
      <p v-if="error" class="err">{{ error }}</p>
      <div v-if="savedId" class="buttons">
        <RouterLink :to="{ name: 'ride-record', params: { id: savedId } }" class="btn primary"
          >Zobrazit jízdu</RouterLink
        >
        <RouterLink :to="{ name: 'routes' }" class="btn">Zpět na trasy</RouterLink>
      </div>
      <div v-else class="buttons">
        <button type="button" class="btn primary" :disabled="saving" @click="emit('save')">
          {{ saving ? 'Ukládám…' : 'Uložit jízdu' }}
        </button>
        <button type="button" class="btn" :disabled="saving" @click="emit('discard')">Zahodit</button>
        <button v-if="!finished" type="button" class="btn" :disabled="saving" @click="emit('resume')">
          Pokračovat v jízdě
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: absolute;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.55);
  padding: 16px;
}
.dialog {
  background: var(--panel-solid);
  border-radius: 12px;
  padding: 20px 22px;
  width: min(420px, 100%);
}
h2 {
  margin: 0 0 14px;
  font-size: 20px;
}
dl {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 6px 16px;
  margin: 0 0 16px;
}
dt {
  color: var(--text-2);
}
dd {
  margin: 0;
  text-align: right;
}
.err {
  color: var(--climb);
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.btn {
  font: inherit;
  font-weight: 600;
  padding: 8px 14px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-decoration: none;
}
.btn.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.btn:disabled {
  opacity: 0.45;
  cursor: default;
}
</style>
