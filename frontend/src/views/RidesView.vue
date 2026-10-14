<script setup lang="ts">
import { onMounted, ref } from 'vue'
import SettingsMenu from '@/components/SettingsMenu.vue'
import { fetchRides } from '@/api'
import { fmtKm, fmtM, fmtTime } from '@/lib/ride'
import type { RideSummary } from '@/types/api'

const rides = ref<RideSummary[] | null>(null)
const error = ref<string | null>(null)
const avg = (v: number | null, unit: string) => (v == null ? '–' : `${Math.round(v)} ${unit}`)
const date = (iso: string) =>
  new Date(iso).toLocaleString('cs-CZ', {
    day: 'numeric',
    month: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

onMounted(async () => {
  document.title = 'OpenRide – jízdy'
  try {
    rides.value = await fetchRides()
  } catch (e) {
    error.value = (e as Error).message
  }
})
</script>

<template>
  <main class="rides">
    <header>
      <h1>Jízdy</h1>
      <nav>
        <RouterLink :to="{ name: 'routes' }">trasy</RouterLink>
        <RouterLink :to="{ name: 'trainer' }">trenažér</RouterLink>
        <SettingsMenu />
      </nav>
    </header>
    <p v-if="error" class="msg">Jízdy se nepodařilo načíst: {{ error }}</p>
    <p v-else-if="!rides" class="msg">Načítám…</p>
    <p v-else-if="!rides.length" class="msg">
      Zatím žádná uložená jízda. Jízda se uloží po dojetí, když ji potvrdíš.
    </p>
    <table v-else>
      <thead>
        <tr>
          <th>Kdy</th>
          <th>Trasa</th>
          <th class="r">Čas</th>
          <th class="r">Vzdálenost</th>
          <th class="r">Stoupání</th>
          <th class="r">Ø výkon</th>
          <th class="r">Ø kadence</th>
          <th class="r">Ø tep</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rides" :key="r.id">
          <td>
            <RouterLink :to="{ name: 'ride-record', params: { id: r.id } }">{{
              date(r.started_at)
            }}</RouterLink>
          </td>
          <td>{{ r.title }}</td>
          <td class="r num">{{ fmtTime(r.duration_s) }}</td>
          <td class="r num">{{ fmtKm(r.distance_m) }}</td>
          <td class="r num">{{ fmtM(r.elev_gain_m) }}</td>
          <td class="r num">{{ avg(r.avg_power, 'W') }}</td>
          <td class="r num">{{ avg(r.avg_rpm, 'rpm') }}</td>
          <td class="r num">{{ avg(r.avg_pulse, 'bpm') }}</td>
        </tr>
      </tbody>
    </table>
  </main>
</template>

<style scoped>
.rides {
  max-width: 1000px;
  margin: 0 auto;
  padding: 16px;
}
header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
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
}
.msg {
  color: var(--text-2);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
th {
  text-align: left;
  font-weight: 600;
  color: var(--text-2);
  border-bottom: 1px solid var(--line);
  padding: 6px 8px;
}
td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--line);
}
.r {
  text-align: right;
  white-space: nowrap;
}
.num {
  font-weight: 400;
}
@media (max-width: 720px) {
  table {
    display: block;
    overflow-x: auto;
  }
}
</style>
