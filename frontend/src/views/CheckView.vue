<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchRoute } from '@/api'
import RouteMap from '@/components/RouteMap.vue'
import SettingsMenu from '@/components/SettingsMenu.vue'
import TimeChart from '@/components/TimeChart.vue'
import YoutubePlayer from '@/components/YoutubePlayer.vue'
import { gradeColor, tokenReader } from '@/lib/draw'
import {
  aheadGrade,
  distToTime,
  elevAt,
  fmtKm,
  fmtM,
  fmtPct,
  fmtTime,
  GRADE_LABEL,
  gradeAt,
  gradeKind,
  latLonAt,
  nearestDist,
  speedAt,
  timeToDist,
} from '@/lib/ride'
import type { RouteDetail } from '@/types/api'

const WINDOWS = [
  { s: 60, label: '±1 min' },
  { s: 120, label: '±2 min' },
  { s: 300, label: '±5 min' },
]
const STATE_LABEL: Record<number, string> = { 1: 'přehrává', 2: 'pozastaveno', 3: 'načítá', 0: 'konec' }

const routeParams = useRoute()
const data = ref<RouteDetail | null>(null)
const error = ref<string | null>(null)
const playerError = ref<string | null>(null)
const player = ref<InstanceType<typeof YoutubePlayer>>()
const time = ref(0)
const state = ref<number | null>(null)
const win = ref(120)
const root = ref<HTMLElement>()

const video = computed(() => data.value?.video ?? null)
const profile = computed(() => data.value?.profile ?? null)
// profile resampled per second of video, i.e. what the rider sees at each moment
const series = computed(() => {
  const v = video.value
  const p = profile.value
  if (!v || !p) return null
  return {
    t: v.timing.t,
    elev: v.timing.dist.map((d) => elevAt(p, d)),
    grade: v.timing.dist.map((d) => gradeAt(p, d)),
  }
})
const dist = computed(() => (video.value ? timeToDist(video.value.timing, time.value) : 0))
const grade = computed(() => (profile.value ? gradeAt(profile.value, dist.value) : 0))
const ahead = computed(() => (profile.value ? aheadGrade(profile.value, dist.value) : null))
const kind = computed(() => gradeKind(grade.value))
const gradeBg = computed(() => (root.value ? gradeColor(tokenReader(root.value), grade.value) : undefined))
const position = computed(() => (profile.value ? latLonAt(profile.value, dist.value) : null))
const end = computed(() => series.value?.t[series.value.t.length - 1] ?? 0)
const status = computed(() => {
  if (playerError.value) return playerError.value
  if (state.value == null) return 'Načítám přehrávač…'
  return `${STATE_LABEL[state.value] ?? 'připraveno'} · ${fmtTime(time.value)} / ${fmtTime(end.value)} · ${fmtKm(dist.value)}`
})

function seek(s: number) {
  time.value = s
  player.value?.seekTo(s)
}

function pick(lat: number, lon: number) {
  if (profile.value && video.value) seek(distToTime(video.value.timing, nearestDist(profile.value, lat, lon)))
}

let raf = 0
function frame() {
  const t = player.value?.currentTime()
  if (t != null && Math.abs(t - time.value) > 0.05) time.value = t
  state.value = player.value?.state() ?? null
  raf = requestAnimationFrame(frame)
}

onMounted(async () => {
  raf = requestAnimationFrame(frame)
  try {
    data.value = await fetchRoute(String(routeParams.params.id))
    document.title = `Kontrola – ${data.value.title}`
  } catch (e) {
    error.value = (e as Error).message
  }
})
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <main ref="root" class="check">
    <div class="nav">
      <RouterLink :to="{ name: 'routes' }">← trasy</RouterLink>
      <SettingsMenu />
    </div>
    <p v-if="error" class="msg">Trasu se nepodařilo načíst: {{ error }}</p>
    <p v-else-if="!data" class="msg">Načítám…</p>
    <p v-else-if="!video || !series" class="msg">
      {{ data.title }} nemá video – kontrola napárování se týká jen tras s videem.
    </p>
    <template v-else>
      <h1>{{ data.title }}: profil po čase videa</h1>
      <div class="top" :class="{ 'has-map': data.segment }">
        <YoutubePlayer
          ref="player"
          class="player"
          :video-id="video.source_id"
          controls
          @error="playerError = $event"
        />
        <div v-if="data.segment" class="map">
          <RouteMap :segment="data.segment" :position="position" attribution @pick="pick" />
        </div>
      </div>
      <div class="status" :class="{ playing: state === 1, error: playerError }">
        <span class="dot" />{{ status }}
      </div>

      <div class="readout">
        <div class="tile hero">
          <div class="icon" :style="{ background: gradeBg }">
            {{ kind === 'flat' ? '→' : kind === 'climb' ? '↗' : '↘' }}
          </div>
          <div>
            <div class="k">{{ GRADE_LABEL[kind] }}</div>
            <div class="v">{{ fmtPct(grade) }}</div>
            <div class="sub">
              {{ ahead ? `dalších ${Math.round(ahead.meters)} m: ${fmtPct(ahead.grade)}` : 'cíl' }}
            </div>
          </div>
        </div>
        <div class="tile">
          <div class="k">Vzdálenost</div>
          <div class="v">{{ fmtKm(dist) }}</div>
        </div>
        <div class="tile">
          <div class="k">Výška</div>
          <div class="v">{{ profile ? fmtM(elevAt(profile, dist)) : '–' }}</div>
        </div>
        <div class="tile">
          <div class="k">Rychlost (timing)</div>
          <div class="v">{{ Math.round(speedAt(video.timing, time)) }} km/h</div>
        </div>
      </div>

      <section class="chart">
        <div class="chart-head">
          <h2>Výškový profil – okolí aktuálního místa</h2>
          <div class="zoom">
            <button
              v-for="z in WINDOWS"
              :key="z.s"
              type="button"
              :aria-pressed="win === z.s"
              @click="win = z.s"
            >
              {{ z.label }}
            </button>
          </div>
        </div>
        <TimeChart v-bind="series" :time="time" :win="win" mode="elev" :height="280" @seek="seek" />
      </section>
      <section class="chart">
        <div class="chart-head"><h2>Sklon – stejné okno</h2></div>
        <TimeChart v-bind="series" :time="time" :win="win" mode="grade" :height="180" @seek="seek" />
      </section>
      <section class="chart">
        <div class="chart-head"><h2>Celé video</h2></div>
        <TimeChart v-bind="series" :time="time" :win="win" mode="overview" :height="90" @seek="seek" />
      </section>
      <p class="note">Klik do grafu nebo na trasu v mapě video přetočí.</p>
    </template>
  </main>
</template>

<style scoped>
.check {
  max-width: 1100px;
  margin: 0 auto;
  padding: 16px;
}
.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 0 8px;
  font-size: 13px;
}
.msg {
  color: var(--text-2);
}
h1 {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 12px;
}
.top {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}
.top.has-map {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
}
.player {
  border-radius: 8px;
  overflow: hidden;
}
.map {
  border-radius: 8px;
  overflow: hidden;
  min-height: 260px;
}
@media (max-width: 760px) {
  .top.has-map {
    grid-template-columns: 1fr;
  }
}
.status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.status .dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--muted);
  flex: none;
}
.status.playing .dot {
  background: #0ca30c;
}
.status.error .dot {
  background: #d03b3b;
}
.readout {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 12px 0;
}
.tile {
  background: var(--surface-2);
  border-radius: 8px;
  padding: 10px 14px;
  min-width: 120px;
}
.tile .k {
  font-size: 12px;
}
.tile .v {
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.hero {
  flex: 1 1 260px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.hero .icon {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 20px;
  color: #fff;
  background: var(--flat);
  flex: none;
}
.hero .v {
  font-size: 30px;
}
.hero .sub {
  font-size: 13px;
  color: var(--text-2);
}
.chart {
  margin-top: 16px;
}
.chart-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 4px;
}
.chart-head h2 {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}
.zoom {
  display: inline-flex;
  border: 1px solid var(--grid);
  border-radius: 6px;
  overflow: hidden;
}
.zoom button {
  font: inherit;
  font-size: 12px;
  padding: 3px 10px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}
.zoom button + button {
  border-left: 1px solid var(--grid);
}
.zoom button[aria-pressed='true'] {
  background: var(--surface-2);
  color: var(--text);
  font-weight: 600;
}
.note {
  font-size: 12px;
  color: var(--muted);
  margin-top: 18px;
}
</style>
