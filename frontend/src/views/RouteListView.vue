<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { fetchRoute, fetchRoutes } from '@/api'
import RouteMap from '@/components/RouteMap.vue'
import SettingsMenu from '@/components/SettingsMenu.vue'
import { fmtPct } from '@/lib/ride'
import { climbPerKm, LENGTHS, matches, type RouteFilter, TERRAINS, terrainOf } from '@/lib/routeFilter'
import type { LatLon, RouteSummary } from '@/types/api'

const routes = ref<RouteSummary[] | null>(null)
const error = ref<string | null>(null)
// list endpoint has no geometry, so virtual routes fetch their detail for the minimap
const segments = reactive<Record<number, LatLon[] | null>>({})

const num = (v: number | null, digits = 0) => (v == null ? '–' : v.toFixed(digits).replace('.', ','))

const FILTER_KEY = 'openride.routeFilter'
function loadFilter(): RouteFilter {
  try {
    return { length: null, terrain: null, ...JSON.parse(localStorage.getItem(FILTER_KEY) ?? '{}') }
  } catch {
    return { length: null, terrain: null }
  }
}
const filter = reactive<RouteFilter>(loadFilter())
watch(filter, () => {
  try {
    localStorage.setItem(FILTER_KEY, JSON.stringify(filter))
  } catch {
    // blocked storage: the filter just resets on reload
  }
})
const shown = computed(() => routes.value?.filter((r) => matches(r, filter)) ?? [])
const terrainLabel = (r: RouteSummary) => TERRAINS.find((t) => t.key === terrainOf(r))?.label

onMounted(async () => {
  document.title = 'OpenRide – trasy'
  try {
    routes.value = await fetchRoutes()
  } catch (e) {
    error.value = (e as Error).message
    return
  }
  for (const r of routes.value.filter((r) => !r.video)) {
    fetchRoute(r.id)
      .then((d) => (segments[r.id] = d.segment))
      .catch(() => (segments[r.id] = null))
  }
})
</script>

<template>
  <main class="list">
    <header>
      <h1>OpenRide</h1>
      <nav>
        <SettingsMenu />
      </nav>
    </header>
    <p v-if="error" class="msg">Trasy se nepodařilo načíst: {{ error }}</p>
    <p v-else-if="!routes" class="msg">Načítám…</p>
    <p v-else-if="!routes.length" class="msg">Zatím tu nejsou žádné zpracované trasy.</p>
    <template v-else>
      <div class="filters">
        <div class="chips" role="group" aria-label="Délka jízdy">
          <button type="button" :aria-pressed="!filter.length" @click="filter.length = null">Vše</button>
          <button
            v-for="l in LENGTHS"
            :key="l.key"
            type="button"
            :aria-pressed="filter.length === l.key"
            @click="filter.length = filter.length === l.key ? null : l.key"
          >
            {{ l.label }}
          </button>
        </div>
        <div class="chips" role="group" aria-label="Terén">
          <button type="button" :aria-pressed="!filter.terrain" @click="filter.terrain = null">Vše</button>
          <button
            v-for="t in TERRAINS"
            :key="t.key"
            type="button"
            :aria-pressed="filter.terrain === t.key"
            @click="filter.terrain = filter.terrain === t.key ? null : t.key"
          >
            {{ t.label }}
          </button>
        </div>
      </div>
      <p v-if="!shown.length" class="msg">Filtru neodpovídá žádná trasa.</p>
      <ul v-else class="tiles">
        <li v-for="r in shown" :key="r.id" class="tile">
          <RouterLink :to="{ name: 'ride', params: { id: r.id } }" class="thumb">
            <img
              v-if="r.video"
              :src="`https://i.ytimg.com/vi/${r.video.source_id}/hqdefault.jpg`"
              :alt="r.title"
              loading="lazy"
            />
            <RouteMap v-else-if="segments[r.id]" :segment="segments[r.id]!" :interactive="false" />
            <span class="badge">{{ r.video ? 'video' : 'virtuální' }}</span>
            <span v-if="r.video?.duration_s" class="badge duration num"
              >{{ Math.round(r.video.duration_s / 60) }} min</span
            >
          </RouterLink>
          <div class="body">
            <RouterLink :to="{ name: 'ride', params: { id: r.id } }" class="title">{{ r.title }}</RouterLink>
            <div class="facts">
              <span
                ><b class="num">{{ num(r.distance_km, 1) }}</b> km</span
              >
              <span
                >↗ <b class="num">{{ num(r.elev_gain_m) }}</b> m</span
              >
              <span
                >↘ <b class="num">{{ num(r.elev_loss_m) }}</b> m</span
              >
              <span
                >max <b class="num">{{ r.max_grade == null ? '–' : fmtPct(r.max_grade) }}</b></span
              >
            </div>
            <div v-if="terrainLabel(r)" class="terrain">
              {{ terrainLabel(r) }} · <span class="num">{{ num(climbPerKm(r)) }}</span> m/km
            </div>
            <RouterLink v-if="r.video" :to="{ name: 'check', params: { id: r.id } }" class="check">
              kontrola napárování
            </RouterLink>
          </div>
        </li>
      </ul>
    </template>
  </main>
</template>

<style scoped>
.list {
  max-width: 1100px;
  margin: 0 auto;
  padding: 16px;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
h1 {
  font-size: 20px;
  margin: 0;
}
header nav {
  display: flex;
  align-items: center;
  gap: 14px;
}
.manage-link {
  font-size: 14px;
  color: var(--text-2);
}
.msg {
  color: var(--text-2);
}
.filters {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chips button {
  font: inherit;
  font-size: 13px;
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}
.chips button[aria-pressed='true'] {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.tiles {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.tile {
  background: var(--surface-2);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.thumb {
  position: relative;
  display: block;
  aspect-ratio: 16 / 9;
  background: var(--line);
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
/* minimap is a preview; the whole tile is the link */
.thumb :deep(.route-map) {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.badge {
  position: absolute;
  left: 8px;
  top: 8px;
  z-index: 500;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  border-radius: 4px;
  padding: 2px 6px;
}
.badge.duration {
  left: auto;
  right: 8px;
  text-transform: none;
  letter-spacing: 0;
}
.terrain {
  font-size: 12px;
  color: var(--text-2);
}
.body {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.title {
  font-weight: 600;
  text-decoration: none;
}
.facts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 13px;
  color: var(--text-2);
}
.check {
  font-size: 12px;
  color: var(--muted);
}
</style>
