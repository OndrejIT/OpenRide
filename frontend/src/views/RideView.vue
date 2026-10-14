<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import RepeatButton from '@/components/RepeatButton.vue'
import RideFinish from '@/components/RideFinish.vue'
import TrackChart from '@/components/TrackChart.vue'
import VirtualScene from '@/components/VirtualScene.vue'
import YoutubePlayer from '@/components/YoutubePlayer.vue'
import { useRideSession } from '@/composables/useRideSession'
import { loadColor } from '@/lib/draw'
import { fmtPct, fmtTime, resistance } from '@/lib/ride'
import { brakeLevel } from '@/lib/trainer'

// Ride screen after the ESP32 dashboard of NaKole (github.com/OndrejIT/NaKole, data/index.html): video over the whole screen, live values
// top left, playback top right, the route chart at the bottom, settings behind the wrench.

const STORE = 'openride.ride'

const {
  data,
  error,
  ride,
  trainer,
  video,
  difficulty,
  trainerInfo,
  live,
  trainerLost,
  record,
  finish,
  saving,
  savedId,
  saveError,
  recordSummary,
  openFinish,
  save,
  discard,
  toggle,
  seek,
  step,
  nextStep,
} = useRideSession({
  keys: {
    Space: playPause,
    KeyG: () => (prefs.track = !prefs.track),
    KeyH: () => (prefs.videoOnly = !prefs.videoOnly),
  },
  onInput: poke,
})

// track = route chart shown, big = the large sizes of the ESP32 original instead of the compact ones,
// videoOnly = nothing over the picture while riding, panel = how solid the value cards are (0 glass … 1 solid),
// autoFullscreen = starting the ride goes full screen (otherwise a button does), fill = the video covers the screen
// (edges cropped) instead of showing whole with black bars
function stored(): {
  track?: boolean
  big?: boolean
  videoOnly?: boolean
  panel?: number
  autoFullscreen?: boolean
  fill?: boolean
} {
  try {
    return JSON.parse(localStorage.getItem(STORE) ?? '{}')
  } catch {
    return {}
  }
}
const prefs = reactive({
  track: true,
  big: false,
  videoOnly: false,
  panel: 0.4,
  autoFullscreen: true,
  fill: true,
  ...stored(),
})
watch(prefs, () => {
  try {
    localStorage.setItem(STORE, JSON.stringify(prefs))
  } catch {
    // private mode: back to the defaults next time
  }
})
const showSettings = ref(false)
// video only: nothing over the picture while riding; a pause (tap) brings everything back
const bare = computed(() => prefs.videoOnly && ride.playing.value && !touched.value && !showSettings.value)

// playback controls in the middle: always while paused, while riding only for a moment after a touch;
// a double tap on the picture starts / pauses right away
const CONTROLS_MS = 3000
const DOUBLE_TAP_MS = 300
const touched = ref(false)
let touchTimer: ReturnType<typeof setTimeout> | undefined
function poke() {
  touched.value = true
  clearTimeout(touchTimer)
  touchTimer = setTimeout(() => (touched.value = false), CONTROLS_MS)
}
const controlsOn = computed(() => (!ride.playing.value || touched.value) && !finish.value)
let lastTap = 0
function onStageTap() {
  const now = Date.now()
  if (now - lastTap < DOUBLE_TAP_MS) {
    lastTap = 0
    playPause()
  } else {
    lastTap = now
  }
  poke()
}
function act(action: () => void) {
  action()
  poke()
}

// grade → 0…1 within the brake levels the grade is spread over; difficulty, range and boost included
const loadOf = computed(() => {
  const k = difficulty.value
  const { lo, hi } = trainer.range.value
  const boost = trainer.settings.boost
  return (grade: number) => (brakeLevel(resistance(grade, k).sim, lo, hi) + boost - lo) / Math.max(hi - lo, 1)
})
const level = computed(() => live.value.brake ?? trainer.levelFor(ride.trainer.value.sim))
// where the shown level sits between the lowest and highest level of the grade range: colour and bars
const levelT = computed(() => {
  const { lo, hi } = trainer.range.value
  return Math.min(1, Math.max(0, (level.value - lo) / Math.max(hi - lo, 1)))
})
const levelColor = computed(() => loadColor(levelT.value))
const BARS = 10
const bars = computed(() =>
  Array.from({ length: BARS }, (_, i) => ({
    on: i < Math.max(1, Math.round(levelT.value * BARS)),
    color: loadColor(i / (BARS - 1)),
  })),
)

// tapping the level opens difficulty and trainer details right at the tile
const resistOpen = ref(false)
const resistTile = ref<HTMLElement>()
function onDocClick(e: MouseEvent) {
  if (resistOpen.value && !resistTile.value?.contains(e.target as Node)) resistOpen.value = false
}
// full screen over Safari's bars; iPadOS before 16.4 only has the webkit-prefixed API
type FsDocument = Document & {
  webkitFullscreenEnabled?: boolean
  webkitFullscreenElement?: Element | null
  webkitExitFullscreen?: () => void
}
type FsElement = HTMLElement & { webkitRequestFullscreen?: () => void }
const fsDoc = document as FsDocument
const canFullscreen = !!(fsDoc.fullscreenEnabled || fsDoc.webkitFullscreenEnabled)
const fullscreen = ref(false)
const onFullscreenChange = () =>
  (fullscreen.value = !!(fsDoc.fullscreenElement || fsDoc.webkitFullscreenElement))
function enterFullscreen() {
  const root = document.documentElement as FsElement
  if (root.requestFullscreen) root.requestFullscreen().catch(() => {})
  else root.webkitRequestFullscreen?.()
}
function toggleFullscreen() {
  if (!fullscreen.value) enterFullscreen()
  else if (fsDoc.exitFullscreen) void fsDoc.exitFullscreen()
  else fsDoc.webkitExitFullscreen?.()
  poke()
}
// starting the ride goes full screen by itself; it has to happen inside the tap (browsers allow it only there)
function playPause() {
  if (!ride.playing.value && prefs.autoFullscreen && canFullscreen && !fullscreen.value) enterFullscreen()
  toggle()
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('webkitfullscreenchange', onFullscreenChange)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
  clearTimeout(touchTimer)
})

const stepLabel = (direction: 1 | -1) => {
  const n = nextStep(direction)
  if (!video.value) return n * 100 >= 1000 ? `${(n * 100) / 1000} km`.replace('.', ',') : `${n * 100} m`
  return n * 10 >= 60 ? `${(n * 10) / 60} min` : `${n * 10} s`
}

const km = (m: number) => (m / 1000).toFixed(1).replace('.', ',')
const signed = (n: number) => `${n > 0 ? '+' : ''}${n}`
const boost = (delta: number) => trainer.setBoost(trainer.settings.boost + delta)
</script>

<template>
  <div
    class="ride theme-dark"
    :class="{ big: prefs.big, whole: video && !prefs.fill }"
    :style="{ '--panel-a': prefs.panel }"
  >
    <p v-if="error" class="msg">
      Trasu se nepodařilo načíst: {{ error }} ·
      <RouterLink :to="{ name: 'routes' }">zpět na trasy</RouterLink>
    </p>
    <template v-else-if="data && ride.profile.value">
      <div class="background" @click="onStageTap">
        <div v-if="video" class="video" :class="{ whole: !prefs.fill }">
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
        <div class="shade" />
      </div>

      <!-- the rider's effort left, the terrain in the middle, the load (the one thing touched while riding) right -->
      <div class="top fades" :class="{ hidden: bare }">
        <div class="left">
          <div class="card effort">
            <div class="label">Výkon</div>
            <div class="value power num">{{ live.power ?? '–' }}<small>W</small></div>
            <div class="sub num">
              <span
                ><b class="rpm">{{ live.rpm ?? '–' }}</b> rpm</span
              >
              <span v-if="live.pulse"
                ><b class="pulse">{{ live.pulse }}</b> bpm</span
              >
            </div>
          </div>
          <div class="card trip">
            <div class="label">Čas</div>
            <div class="value time num">{{ fmtTime(ride.time.value) }}</div>
            <div v-if="ride.duration.value != null" class="sub num">/ {{ fmtTime(ride.duration.value) }}</div>
          </div>
          <div class="card trip">
            <div class="label">Vzdálenost</div>
            <div class="value dist num">{{ km(ride.dist.value) }}<small>km</small></div>
            <div class="sub num">/ {{ km(ride.length.value) }} km</div>
          </div>
        </div>

        <div class="card terrain">
          <div class="label">Stoupání</div>
          <div class="value incline num">{{ fmtPct(ride.grade.value) }}</div>
          <div v-if="ride.ahead.value" class="sub num">
            dalších {{ Math.round(ride.ahead.value.meters) }} m {{ fmtPct(ride.ahead.value.grade) }}
          </div>
          <div v-else class="sub">cíl</div>
        </div>

        <div ref="resistTile" class="card resist">
          <div class="label">Zátěž</div>
          <button
            type="button"
            class="value num level"
            :style="{ color: levelColor }"
            aria-label="Obtížnost a trenažér"
            :aria-expanded="resistOpen"
            @click="resistOpen = !resistOpen"
          >
            {{ level }}
          </button>
          <div class="bars" aria-hidden="true">
            <span
              v-for="(b, i) in bars"
              :key="i"
              :style="{ height: `${30 + i * 7}%`, background: b.on ? b.color : undefined }"
            />
          </div>
          <div class="load-controls">
            <RepeatButton aria-label="Lehčí" @step="boost(-1)"
              ><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 11h14v2H5Z" /></svg
            ></RepeatButton>
            <span class="num">{{ signed(trainer.settings.boost) }}</span>
            <RepeatButton aria-label="Těžší" @step="boost(1)"
              ><svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6Z" /></svg
            ></RepeatButton>
          </div>
          <div v-if="resistOpen" class="resist-pop card">
            <label class="setting">
              <span>Obtížnost: {{ Math.round(difficulty * 100) }} %</span>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                :value="Math.round(difficulty * 100)"
                @input="difficulty = Number(($event.target as HTMLInputElement).value) / 100"
              />
            </label>
            <small
              >sklon {{ fmtPct(ride.grade.value) }} → simulovaný {{ fmtPct(ride.trainer.value.sim) }}</small
            >
            <RouterLink :to="{ name: 'trainer' }" class="trainer" :class="{ on: trainerInfo?.connected }">
              <template v-if="trainerInfo?.connected"
                >● {{ trainerInfo.name }} · brzda {{ trainerInfo.brake ?? '–' }}/{{
                  trainerInfo.brakeMax
                }}</template
              >
              <template v-else-if="trainerInfo">○ Most připojen, Kettler ne</template>
              <template v-else>○ Trenažér nepřipojen</template>
            </RouterLink>
          </div>
        </div>
      </div>

      <div class="center fades" :class="{ hidden: !controlsOn }">
        <button type="button" class="ctl" :aria-label="`Zpět ${stepLabel(-1)}`" @click="act(() => step(-1))">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M11 18V6l-8.5 6 8.5 6Zm.5-6 8.5 6V6l-8.5 6Z" />
          </svg>
          <small>{{ stepLabel(-1) }}</small>
        </button>
        <button
          type="button"
          class="ctl main"
          :class="{ paused: !ride.playing.value }"
          :aria-label="ride.playing.value ? 'Pauza' : 'Přehrát'"
          @click="act(playPause)"
        >
          <svg v-if="ride.playing.value" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 19h4V5H6v14Zm8-14v14h4V5h-4Z" />
          </svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7Z" /></svg>
        </button>
        <button type="button" class="ctl" :aria-label="`Vpřed ${stepLabel(1)}`" @click="act(() => step(1))">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 18l8.5-6L4 6v12Zm9-12v12l8.5-6L13 6Z" />
          </svg>
          <small>{{ stepLabel(1) }}</small>
        </button>
      </div>

      <div v-if="trainerLost" class="warn">Kettler odpojen</div>

      <div v-if="prefs.track" class="bottom fades" :class="{ hidden: bare }" @pointerdown="poke">
        <TrackChart
          :profile="ride.profile.value"
          :dist="ride.dist.value"
          :load="loadOf"
          :controls="controlsOn"
          @seek="seek"
        />
      </div>
      <button
        type="button"
        class="track-toggle fades"
        :class="{ hidden: bare }"
        :aria-label="prefs.track ? 'Skrýt graf trati' : 'Zobrazit graf trati'"
        @click="prefs.track = !prefs.track"
      >
        {{ prefs.track ? '▼' : '▲' }}
      </button>

      <!-- stop, back and settings together, shown with the playback controls -->
      <div class="actions fades" :class="{ hidden: !controlsOn && !showSettings, low: !prefs.track }">
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
        <button
          v-if="record.t.length && !savedId"
          type="button"
          class="icon"
          title="Ukončit jízdu a uložit záznam"
          aria-label="Ukončit jízdu"
          @click="openFinish(false)"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6h12v12H6Z" /></svg>
        </button>
        <RouterLink :to="{ name: 'routes' }" class="icon" title="Seznam tras" aria-label="Seznam tras">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2Z" />
          </svg>
        </RouterLink>
        <button
          v-if="canFullscreen && !prefs.autoFullscreen"
          type="button"
          class="icon"
          :aria-label="fullscreen ? 'Zrušit celou obrazovku' : 'Celá obrazovka'"
          @click="toggleFullscreen"
        >
          <svg v-if="fullscreen" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 16h3v3h2v-5H5v2Zm3-8H5v2h5V5H8v3Zm6 11h2v-3h3v-2h-5v5Zm2-11V5h-2v5h5V8h-3Z" />
          </svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true">
            <path d="M7 14H5v5h5v-2H7v-3Zm-2-4h2V7h3V5H5v5Zm12 7h-3v2h5v-5h-2v3ZM14 5v2h3v3h2V5h-5Z" />
          </svg>
        </button>
        <button type="button" class="icon" aria-label="Nastavení" @click.stop="showSettings = !showSettings">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4Z"
            />
          </svg>
        </button>
      </div>
      <template v-if="showSettings">
        <div class="backdrop" @click="showSettings = false" />
        <div class="settings card" :class="{ low: !prefs.track }">
          <h2>Nastavení</h2>
          <div class="col">
            <h3>Jízda</h3>
            <label class="setting">
              <span>Obtížnost: {{ Math.round(difficulty * 100) }} %</span>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                :value="Math.round(difficulty * 100)"
                @input="difficulty = Number(($event.target as HTMLInputElement).value) / 100"
              />
              <small>simulovaný sklon {{ fmtPct(ride.trainer.value.sim) }} · brzda {{ level }}</small>
            </label>
            <div class="setting">
              <span>Přitvrdit brzdu <small>(podržením rychle)</small></span>
              <div class="adjust">
                <RepeatButton class="panel-btn" aria-label="Lehčí" @step="boost(-1)"
                  ><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 11h14v2H5Z" /></svg
                ></RepeatButton>
                <b class="num">{{ signed(trainer.settings.boost) }}</b>
                <RepeatButton class="panel-btn" aria-label="Těžší" @step="boost(1)"
                  ><svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6Z" /></svg
                ></RepeatButton>
              </div>
            </div>
            <label class="setting check">
              <input
                type="checkbox"
                :checked="trainer.settings.autoPause"
                @change="trainer.setAutoPause(($event.target as HTMLInputElement).checked)"
              />
              <span>Pozastavit video, když nešlapu</span>
            </label>
          </div>
          <div class="col">
            <h3>Vzhled</h3>
            <label class="setting">
              <span>Pozadí karet: {{ Math.round(prefs.panel * 100) }} %</span>
              <input v-model.number="prefs.panel" type="range" min="0" max="1" step="0.05" />
              <small>0 % = jen sklo, 100 % = plné tmavé karty</small>
            </label>
            <label class="setting check">
              <input v-model="prefs.fill" type="checkbox" />
              <span
                >Video přes celou obrazovku <small>(ořízne okraje; jinak celé s černými pruhy)</small></span
              >
            </label>
            <label v-if="canFullscreen" class="setting check">
              <input v-model="prefs.autoFullscreen" type="checkbox" />
              <span>Celá obrazovka při startu jízdy <small>(jinak tlačítko vpravo dole)</small></span>
            </label>
            <label class="setting check">
              <input v-model="prefs.big" type="checkbox" />
              <span>Velká čísla a tlačítka</span>
            </label>
            <label class="setting check">
              <input v-model="prefs.videoOnly" type="checkbox" />
              <span>Při jízdě jen video <small>(klávesa H; klepnutí nebo pauza vše ukáže)</small></span>
            </label>
          </div>
          <RouterLink :to="{ name: 'trainer' }" class="trainer" :class="{ on: trainerInfo?.connected }">
            <template v-if="trainerInfo?.connected"
              >● {{ trainerInfo.name }} · brzda {{ trainerInfo.brake ?? '–' }}/{{
                trainerInfo.brakeMax
              }}</template
            >
            <template v-else-if="trainerInfo">○ Most připojen, Kettler ne</template>
            <template v-else>○ Trenažér nepřipojen</template>
          </RouterLink>
        </div>
      </template>
    </template>
    <RideFinish
      v-if="finish"
      :summary="recordSummary"
      :finished="finish.finished"
      :saving="saving"
      :saved-id="savedId"
      :error="saveError"
      @save="save"
      @discard="discard"
      @resume="finish = null"
    />
    <p v-else-if="!data && !error" class="msg">Načítám…</p>
  </div>
</template>

<style scoped>
/* colours and glass cards of the ESP32 dashboard; theme-dark gives shared parts (end-of-ride dialog) dark tokens */
.ride.big {
  --z: 1;
}
.ride {
  --track-h: max(15vh, 100px);
}
/* a whole video on a screen taller than 16:9 leaves black bars above and below: the cards move into the top one,
   the route chart fills the bottom one */
@media (max-aspect-ratio: 16/9) {
  .ride.whole {
    /* dvh: Safari's 100vh includes its toolbars, which would push the cards below the middle of the bar */
    --bar: calc((100dvh - 56.25vw) / 2);
    --track-h: max(70px, var(--bar));
  }
  .ride.whole .top,
  .ride.whole .left {
    align-items: center;
  }
  .ride.whole .top {
    min-height: var(--bar);
    align-content: center;
    padding-top: calc(8px + env(safe-area-inset-top));
    padding-bottom: 8px;
  }
  /* one row per card (label, number, details side by side) so the cards fit the bar instead of the picture */
  .ride.whole .top .card {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    padding: 6px 14px;
  }
  .ride.whole .top .label {
    margin: 0;
  }
  .ride.whole .top .sub {
    flex-direction: column;
    align-items: flex-start;
    gap: 0;
    margin: 0;
    text-align: left;
  }
  .ride.whole .resist .level {
    width: auto;
  }
  .ride.whole .resist .bars {
    width: 60px;
    margin: 0;
  }
  .ride.whole .resist .load-controls {
    margin: 0;
  }
}
.ride {
  --cyan: #00d4ff;
  --orange: #ff9f43;
  --purple: #a29bfe;
  --green: #00ff88;
  --pink: #ff6b9d;
  /* size of the panels: compact by default, the ESP32 original with "big" */
  --z: 0.72;
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: #1a1a2e;
  color: #fff;
}
/* video only: everything fades out while riding and comes back on pause */
.fades {
  transition: opacity 0.3s;
}
.fades.hidden {
  opacity: 0;
}
/* children too: the stats and buttons switch their own pointer events back on */
.fades.hidden,
.fades.hidden * {
  pointer-events: none;
}
.msg {
  padding: 24px;
  color: rgba(255, 255, 255, 0.7);
}
.background {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
}
/* the video covers the screen: cropped at the edges rather than letterboxed */
.video {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100vw;
  height: 56.25vw;
  min-width: 177.78dvh;
  min-height: 100dvh;
  transform: translate(-50%, -50%);
}
/* the whole picture instead: as large as fits, black bars where the screen's shape differs */
.video.whole {
  width: min(100vw, 177.78dvh);
  height: min(100dvh, 56.25vw);
  min-width: 0;
  min-height: 0;
}
.video :deep(.yt) {
  height: 100%;
}
.shade {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.15);
  pointer-events: none;
}
/* dark glass: reads on bright sky better than white glass; how solid it is follows the rider's setting */
.card {
  --a: var(--panel-a, 0.4);
  /* 0 % = nothing at all: tint, blur, outline and shadow all fade with the setting */
  background: rgba(16, 16, 28, var(--a));
  backdrop-filter: blur(min(12px, calc(var(--a) * 30px)));
  -webkit-backdrop-filter: blur(min(12px, calc(var(--a) * 30px)));
  border: 1px solid rgba(255, 255, 255, min(0.12, calc(var(--a) * 0.3)));
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, min(0.3, calc(var(--a) * 0.75)));
  padding: calc(12px * var(--z));
}
.top {
  /* above the route chart: the level details open downwards */
  z-index: 1;
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  /* effort left, terrain centred on the screen, load right */
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: start;
  gap: calc(20px * var(--z));
  padding: calc(20px * var(--z));
  /* clear of the status bar when running as a home screen web app */
  padding-top: calc(20px * var(--z) + env(safe-area-inset-top));
  pointer-events: none;
}
.top > * {
  pointer-events: auto;
}
/* a shadow keeps the numbers readable when the card is mostly or entirely see-through */
.top .card {
  text-shadow:
    0 1px 2px rgba(0, 0, 0, 0.8),
    0 0 8px rgba(0, 0, 0, 0.4);
}
/* effort, then time and distance */
.left {
  justify-self: start;
  display: flex;
  align-items: flex-start;
  gap: calc(12px * var(--z));
}
.trip {
  min-width: calc(110px * var(--z));
  padding: calc(12px * var(--z)) calc(16px * var(--z));
  text-align: center;
}
.terrain {
  text-align: center;
}
.resist {
  justify-self: end;
  text-align: center;
}
.effort,
.terrain,
.resist {
  min-width: calc(150px * var(--z));
  padding: calc(12px * var(--z)) calc(18px * var(--z));
}
.value small {
  margin-left: 4px;
  font-size: 0.45em;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.7);
}
.sub {
  display: flex;
  justify-content: center;
  gap: calc(14px * var(--z));
  margin-top: calc(2px * var(--z));
  font-size: max(0.75rem, calc(1rem * var(--z)));
  color: rgba(255, 255, 255, 0.8);
}
.effort .sub {
  justify-content: flex-start;
}
.sub b {
  font-size: 1.25em;
}
.rpm {
  color: var(--cyan);
}
.pulse {
  color: var(--pink);
}
.label {
  margin-bottom: calc(4px * var(--z));
  font-size: max(0.6rem, calc(0.7rem * var(--z)));
  letter-spacing: 1px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.7);
}
/* the main number of each card: power, grade and load are the same size */
.value {
  font-size: calc(2.6rem * var(--z));
  font-weight: 700;
  line-height: 1.1;
}
.value.power {
  color: #feca57;
}
.value.time {
  color: var(--purple);
}
.value.dist {
  color: var(--green);
}
.value.incline {
  color: var(--orange);
}
.resist {
  position: relative;
}
.level {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  font-family: inherit;
  cursor: pointer;
}
.bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: calc(18px * var(--z));
  margin-top: calc(4px * var(--z));
}
.bars span {
  flex: 1;
  border-radius: 1px;
  background: rgba(255, 255, 255, 0.2);
}
.resist-pop {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 240px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  text-align: left;
  z-index: 2;
}
.resist-pop small {
  font-size: 0.8rem;
  color: var(--text-2);
}
.load-controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: calc(8px * var(--z));
  margin-top: calc(6px * var(--z));
}
/* touch targets do not shrink below a finger */
/* svg icons instead of − / + glyphs, which most fonts draw off centre */
.load-controls button {
  display: grid;
  place-items: center;
  padding: 0;
  width: max(28px, calc(32px * var(--z)));
  height: max(28px, calc(32px * var(--z)));
  border: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  font: inherit;
  font-size: calc(1.2rem * var(--z));
  cursor: pointer;
}
.load-controls span {
  min-width: 30px;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.6);
}
/* stop, back and settings just above the route chart */
.actions {
  position: absolute;
  right: calc(20px * var(--z));
  bottom: calc(var(--track-h) + 14px * var(--z));
  display: flex;
  align-items: center;
  gap: calc(12px * var(--z));
  z-index: 3;
}
.actions.low {
  bottom: calc(20px * var(--z));
}
/* playback, stop and back: light dark-glass discs that read as buttons on bright sky and dark forest alike */
.ctl,
.icon {
  --disc: max(44px, calc(116px * var(--z)));
  display: grid;
  place-content: center;
  justify-items: center;
  width: var(--disc);
  height: var(--disc);
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.3);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: #fff;
  font: inherit;
  text-decoration: none;
  cursor: pointer;
  pointer-events: auto;
  transition:
    transform 0.12s,
    background 0.12s;
}
.ctl:hover,
.icon:hover {
  background: rgba(0, 0, 0, 0.4);
}
/* a short press feedback: the disc darkens and gives way a little */
.ctl:active,
.icon:active {
  transform: scale(0.94);
  background: rgba(0, 0, 0, 0.5);
}
.ctl svg,
.icon svg {
  width: calc(var(--disc) * 0.45);
  height: calc(var(--disc) * 0.45);
  fill: currentColor;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.6));
}
.ctl.main {
  --disc: max(64px, calc(164px * var(--z)));
}
.ctl.main svg {
  width: calc(var(--disc) * 0.55);
  height: calc(var(--disc) * 0.55);
}
/* paused: the way on is the play disc */
.ctl.main.paused {
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.55);
}
.ctl small {
  margin-top: -2px;
  font-size: max(0.7rem, calc(0.85rem * var(--z)));
  font-weight: 600;
  white-space: nowrap;
}
.icon {
  --disc: max(44px, calc(72px * var(--z)));
}
.center {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: calc(48px * var(--z));
  pointer-events: none;
}
.speed {
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
}
.speed input {
  flex: 1;
  accent-color: var(--cyan);
}
.warn {
  position: absolute;
  top: calc(20px + env(safe-area-inset-top));
  left: 50%;
  transform: translateX(-50%);
  padding: 8px 14px;
  border-radius: 12px;
  font-weight: 600;
  background: rgba(227, 73, 72, 0.85);
  pointer-events: none;
}
.bottom {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
}
.track-toggle {
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 60px;
  height: 24px;
  border: 0;
  border-radius: 8px 8px 0 0;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  color: #fff;
  font-size: 0.9rem;
  cursor: pointer;
}
.backdrop {
  position: absolute;
  inset: 0;
  z-index: 1;
}
/* opens above the action buttons */
.settings {
  position: absolute;
  right: calc(20px * var(--z));
  bottom: calc(var(--track-h) + 14px * var(--z) + max(44px, calc(72px * var(--z))) + 10px);
  /* two columns (ride, look) so everything fits without scrolling, which a tablet does not hint at */
  width: min(620px, calc(100vw - 40px));
  max-height: calc(100dvh - var(--track-h) - max(44px, calc(72px * var(--z))) - 60px);
  overflow-y: auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 24px;
  z-index: 2;
}
.settings h2,
.settings .trainer {
  grid-column: 1 / -1;
}
.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.settings h3 {
  margin: 0;
  font-size: 12px;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--text-2);
}
@media (max-width: 560px) {
  .settings {
    grid-template-columns: 1fr;
  }
}
/* the settings and the level details look like the end-of-ride dialog: solid dark panel, accent orange */
.card.settings,
.card.resist-pop {
  padding: 20px 22px;
  border: 0;
  border-radius: 12px;
  background: var(--panel-solid);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  color: var(--text);
}
.card.resist-pop {
  padding: 14px 16px;
}
.load-controls svg,
.panel-btn svg {
  width: 60%;
  height: 60%;
  fill: currentColor;
}
.panel-btn {
  display: grid;
  place-items: center;
  width: 44px;
  height: 36px;
  font: inherit;
  font-weight: 600;
  padding: 0;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text);
  cursor: pointer;
}
.settings.low {
  bottom: calc(20px * var(--z) + max(44px, calc(72px * var(--z))) + 10px);
}
.settings h2 {
  margin: 0;
  font-size: 20px;
}
.setting {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 0.9rem;
}
.setting input {
  accent-color: var(--accent);
}
.setting small {
  color: var(--text-2);
}
.setting.check {
  flex-direction: row;
  align-items: center;
  cursor: pointer;
}
.adjust {
  display: flex;
  align-items: center;
  gap: 10px;
}
.adjust b {
  min-width: 2em;
  text-align: center;
}
.trainer {
  font-size: 0.85rem;
  color: var(--text-2);
  text-decoration: none;
}
.trainer.on {
  color: var(--accent);
}
@media (max-width: 760px) {
  .ride {
    --z: 0.6;
  }
  .ride.big {
    --z: 0.8;
  }
}
</style>
