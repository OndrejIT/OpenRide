<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchRoute } from '@/api'
import AheadProfile from '@/components/AheadProfile.vue'
import GradeHud from '@/components/GradeHud.vue'
import ResistancePanel from '@/components/ResistancePanel.vue'
import RouteMap from '@/components/RouteMap.vue'
import RouteProfile from '@/components/RouteProfile.vue'
import VirtualScene from '@/components/VirtualScene.vue'
import YoutubePlayer from '@/components/YoutubePlayer.vue'
import { useRide } from '@/composables/useRide'
import { fmtKm, fmtM, fmtTime } from '@/lib/ride'
import type { RouteDetail } from '@/types/api'

const DIFFICULTY_STEP = 0.05

const routeParams = useRoute()
const data = ref<RouteDetail | null>(null)
const error = ref<string | null>(null)
const ride = useRide(data)
const player = ref<InstanceType<typeof YoutubePlayer>>()

const video = computed(() => data.value?.video ?? null)
const difficulty = computed({ get: () => ride.difficulty.value, set: ride.setDifficulty })
const timeLabel = computed(() =>
  ride.duration.value != null
    ? `${fmtTime(ride.time.value)} / ${fmtTime(ride.duration.value)}`
    : fmtTime(ride.time.value),
)

function toggle() {
  if (video.value) {
    if (ride.playing.value) player.value?.pause()
    else player.value?.play()
  } else if (ride.dist.value < ride.length.value) {
    ride.playing.value = !ride.playing.value
  }
}

function seek(d: number) {
  const s = ride.seekDist(d)
  if (s != null) player.value?.seekTo(s)
}

function step(direction: 1 | -1) {
  const s = ride.step(direction)
  if (s != null) player.value?.seekTo(s)
}

function onKey(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  if (
    t &&
    (t.tagName === 'SELECT' ||
      t.tagName === 'TEXTAREA' ||
      (t.tagName === 'INPUT' && t.getAttribute('type') !== 'range'))
  )
    return
  const actions: Record<string, () => void> = {
    Space: toggle,
    ArrowRight: () => step(1),
    ArrowLeft: () => step(-1),
    ArrowUp: () => ride.setDifficulty(ride.difficulty.value + DIFFICULTY_STEP),
    ArrowDown: () => ride.setDifficulty(ride.difficulty.value - DIFFICULTY_STEP),
  }
  const action = actions[e.code]
  if (!action) return
  // also stops a focused slider from moving on its own
  e.preventDefault()
  action()
}

// the player (video) or the wall clock (virtual) drives the position
let raf = 0
let lastFrame = 0
function frame(now: number) {
  const dt = lastFrame ? Math.min(0.25, (now - lastFrame) / 1000) : 0
  lastFrame = now
  if (video.value) {
    const t = player.value?.currentTime()
    if (t != null && Math.abs(t - ride.videoTime.value) > 0.05) ride.setVideoTime(t)
  } else {
    ride.advance(dt)
  }
  raf = requestAnimationFrame(frame)
}

onMounted(async () => {
  addEventListener('keydown', onKey)
  raf = requestAnimationFrame(frame)
  try {
    data.value = await fetchRoute(String(routeParams.params.id))
    document.title = `Trenažér – ${data.value.title}`
  } catch (e) {
    error.value = (e as Error).message
  }
})

onBeforeUnmount(() => {
  removeEventListener('keydown', onKey)
  cancelAnimationFrame(raf)
})
</script>

<template>
  <div class="ride theme-dark">
    <p v-if="error" class="msg">
      Trasu se nepodařilo načíst: {{ error }} ·
      <RouterLink :to="{ name: 'routes' }">zpět na trasy</RouterLink>
    </p>
    <template v-else-if="data && ride.profile.value">
      <div class="stage">
        <div v-if="video" class="video">
          <YoutubePlayer
            ref="player"
            :video-id="video.source_id"
            @playing="ride.playing.value = $event"
            @error="error = $event"
          />
        </div>
        <VirtualScene
          v-else-if="data.segment && ride.latLon.value"
          :segment="data.segment"
          :position="ride.latLon.value"
          :heading="ride.heading.value"
        />
        <p v-else class="msg">Trasa nemá souřadnice, průlet nelze zobrazit.</p>
      </div>

      <GradeHud class="panel grade" :grade="ride.grade.value" :ahead="ride.ahead.value" />
      <ResistancePanel
        v-model:difficulty="difficulty"
        class="panel resist"
        :sim="ride.trainer.value.sim"
        :level="ride.trainer.value.level"
      />

      <div class="panel stats">
        <span class="k">Čas</span><span class="num">{{ timeLabel }}</span> <span class="k">Vzdálenost</span
        ><span class="num">{{ fmtKm(ride.dist.value) }}</span> <span class="k">Výška</span
        ><span class="num">{{ fmtM(ride.elev.value) }}</span>
        <span class="k">{{ video ? 'Rychlost videa' : 'Rychlost' }}</span>
        <span class="num">{{ Math.round(ride.speed.value) }} km/h</span>
      </div>
      <div v-if="data.segment" class="panel map">
        <RouteMap :segment="data.segment" :position="ride.latLon.value" :interactive="false" />
      </div>

      <div class="panel bottom">
        <div class="head">
          <div class="controls">
            <RouterLink :to="{ name: 'routes' }" class="btn" title="Seznam tras">←</RouterLink>
            <button type="button" class="btn" @click="toggle">
              {{ ride.playing.value ? '❚❚ Pauza' : '▶ Start' }}
            </button>
            <label v-if="!video" class="speed">
              <input
                v-model.number="ride.speedKmh.value"
                type="range"
                min="0"
                max="60"
                step="1"
                aria-label="Rychlost"
              />
              <span class="num">{{ ride.speedKmh.value }} km/h</span>
            </label>
            <span class="title">{{ data.title }}</span>
          </div>
          <span class="hint">
            mezera = start/pauza · ←/→ = {{ video ? '±10 s' : '±100 m' }} · ↑/↓ = obtížnost · klik do profilu
            = skok
          </span>
        </div>
        <AheadProfile :profile="ride.profile.value" :dist="ride.dist.value" />
        <RouteProfile :profile="ride.profile.value" :dist="ride.dist.value" @seek="seek" />
      </div>
    </template>
    <p v-else class="msg">Načítám…</p>
  </div>
</template>

<style scoped>
.ride {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font-size: 15px;
  line-height: 1.35;
}
.msg {
  padding: 24px;
  color: var(--text-2);
}
.stage {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: #000;
}
.video {
  position: relative;
  width: min(100vw, calc(100vh * 16 / 9));
}
.panel {
  position: absolute;
  background: var(--panel);
  backdrop-filter: blur(6px);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.grade {
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
}
.resist {
  top: 16px;
  left: 16px;
}
.stats {
  top: 16px;
  right: 16px;
  padding: 10px 14px;
  display: grid;
  grid-template-columns: auto auto;
  gap: 4px 16px;
  min-width: 210px;
  align-items: baseline;
}
.stats .num {
  font-size: 20px;
  text-align: right;
}
.map {
  top: 150px;
  right: 16px;
  width: 240px;
  height: 180px;
  overflow: hidden;
}
.bottom {
  left: 16px;
  right: 16px;
  bottom: 16px;
  padding: 10px 12px 8px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.controls {
  display: flex;
  gap: 8px;
  align-items: center;
  min-width: 0;
}
.btn {
  font: inherit;
  font-size: 13px;
  color: var(--text);
  background: var(--panel-solid);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  text-decoration: none;
}
.speed {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.speed input {
  accent-color: var(--accent);
  width: 120px;
}
.title {
  font-size: 13px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hint {
  font-size: 11px;
  color: var(--muted);
}
@media (max-width: 760px) {
  .map {
    display: none;
  }
  .stats {
    top: auto;
    bottom: 200px;
  }
}
</style>
