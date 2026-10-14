<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchRide } from '@/api'
import RideChart from '@/components/RideChart.vue'
import SettingsMenu from '@/components/SettingsMenu.vue'
import { fmtKm, fmtM, fmtTime } from '@/lib/ride'
import type { RideDetail } from '@/types/api'

const params = useRoute()
const ride = ref<RideDetail | null>(null)
const error = ref<string | null>(null)
const hover = ref<number | null>(null)

const avg = (v: number | null, unit: string) => (v == null ? '–' : `${Math.round(v)} ${unit}`)
const started = computed(() =>
  ride.value
    ? new Date(ride.value.started_at).toLocaleString('cs-CZ', { dateStyle: 'long', timeStyle: 'short' })
    : '',
)
const at = computed(() => {
  const s = ride.value?.samples
  if (!s || hover.value == null) return null
  return { t: s.t[hover.value]!, dist: s.dist[hover.value]! }
})

onMounted(async () => {
  try {
    ride.value = await fetchRide(String(params.params.id))
    document.title = `Jízda – ${ride.value.title}`
  } catch (e) {
    error.value = (e as Error).message
  }
})
</script>

<template>
  <main class="record">
    <header>
      <h1>{{ ride?.title ?? 'Jízda' }}</h1>
      <nav>
        <RouterLink :to="{ name: 'rides' }">všechny jízdy</RouterLink>
        <RouterLink v-if="ride?.route" :to="{ name: 'ride', params: { id: ride.route } }"
          >jet znovu</RouterLink
        >
        <SettingsMenu />
      </nav>
    </header>
    <p v-if="error" class="msg">Jízdu se nepodařilo načíst: {{ error }}</p>
    <p v-else-if="!ride" class="msg">Načítám…</p>
    <template v-else>
      <p class="msg">{{ started }}</p>
      <dl class="facts">
        <div>
          <dt>Čas jízdy</dt>
          <dd class="num">{{ fmtTime(ride.duration_s) }}</dd>
        </div>
        <div>
          <dt>Vzdálenost</dt>
          <dd class="num">{{ fmtKm(ride.distance_m) }}</dd>
        </div>
        <div>
          <dt>Stoupání</dt>
          <dd class="num">{{ fmtM(ride.elev_gain_m) }}</dd>
        </div>
        <div>
          <dt>Výkon Ø / max</dt>
          <dd class="num">{{ avg(ride.avg_power, 'W') }} / {{ avg(ride.max_power, 'W') }}</dd>
        </div>
        <div>
          <dt>Kadence Ø</dt>
          <dd class="num">{{ avg(ride.avg_rpm, 'rpm') }}</dd>
        </div>
        <div>
          <dt>Tep Ø / max</dt>
          <dd class="num">{{ avg(ride.avg_pulse, 'bpm') }} / {{ avg(ride.max_pulse, 'bpm') }}</dd>
        </div>
      </dl>

      <p class="cursor-info">
        <template v-if="at">{{ fmtTime(at.t) }} · {{ fmtKm(at.dist) }}</template>
        <template v-else>Najeď do grafu pro hodnoty v daném okamžiku.</template>
      </p>
      <div class="charts">
        <RideChart
          title="Výška"
          unit="m"
          :values="ride.samples.elev"
          area
          :hover="hover"
          @hover="hover = $event"
        />
        <RideChart
          title="Simulovaný sklon"
          unit="%"
          :digits="1"
          :values="ride.samples.sim"
          :hover="hover"
          @hover="hover = $event"
        />
        <RideChart
          title="Brzda"
          unit=""
          :values="ride.samples.brake"
          step
          :hover="hover"
          @hover="hover = $event"
        />
        <RideChart
          title="Výkon"
          unit="W"
          :values="ride.samples.power"
          :hover="hover"
          @hover="hover = $event"
        />
        <RideChart
          title="Kadence"
          unit="rpm"
          :values="ride.samples.rpm"
          :hover="hover"
          @hover="hover = $event"
        />
        <RideChart
          title="Tep"
          unit="bpm"
          :values="ride.samples.pulse"
          :hover="hover"
          @hover="hover = $event"
        />
      </div>
    </template>
  </main>
</template>

<style scoped>
.record {
  max-width: 900px;
  margin: 0 auto;
  padding: 16px;
}
header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
h1 {
  font-size: 20px;
  margin: 0;
}
nav {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 14px;
  white-space: nowrap;
}
.msg {
  color: var(--text-2);
}
.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin: 12px 0;
}
.facts div {
  background: var(--surface-2);
  border-radius: 8px;
  padding: 8px 10px;
}
dt {
  font-size: 12px;
  color: var(--text-2);
}
dd {
  margin: 2px 0 0;
  font-size: 16px;
}
.cursor-info {
  font-size: 13px;
  color: var(--text-2);
  min-height: 1.4em;
}
.charts {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
</style>
