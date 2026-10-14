<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { loadColor } from '@/lib/draw'
import { fmtKm, routeLength } from '@/lib/ride'
import type { Profile } from '@/types/api'

// Elevation along the route as in the ESP32 dashboard (NaKole): the area under the curve coloured by the
// trainer load there, cursor line and dot, zoom around the rider; click = jump there.
// `load` = grade → 0 (easiest brake level) … 1 (hardest), the same mapping the trainer gets.
// `controls` = show the zoom buttons (the ride screen hides them with its other controls)
const props = defineProps<{
  profile: Profile
  dist: number
  load: (grade: number) => number
  controls: boolean
}>()
const emit = defineEmits<{ seek: [dist: number] }>()

const ZOOM_STEP = 1.5
const ZOOM_MAX = 10
// load colour steps: fewer, longer runs to draw and a scale the eye can tell apart
const LOAD_STEPS = 12
const RIDDEN_FADE = 0.45
const LABEL = '12px system-ui, -apple-system, sans-serif'

const canvas = ref<HTMLCanvasElement>()
const zoom = ref(1)
// left edge of the visible window [m]; follows the rider unless scrolled away by hand
const offset = ref(0)
const length = computed(() => routeLength(props.profile))
const span = computed(() => length.value / zoom.value)

const clampOffset = (o: number) => Math.max(0, Math.min(length.value - span.value, o))

function follow() {
  // recentre once the rider gets near the edge of the window, not every frame (the picture would crawl)
  const ideal = clampOffset(props.dist - span.value / 2)
  if (Math.abs(offset.value - ideal) > span.value * 0.4) offset.value = ideal
}

function zoomBy(k: number) {
  zoom.value = Math.min(ZOOM_MAX, Math.max(1, zoom.value * k))
  offset.value = clampOffset(props.dist - span.value / 2)
}
function scroll(direction: 1 | -1) {
  offset.value = clampOffset(offset.value + (direction * span.value) / 10)
}

function draw() {
  const c = canvas.value
  if (!c) return
  const dpr = window.devicePixelRatio || 1
  const w = c.clientWidth
  const h = c.clientHeight
  c.width = Math.round(w * dpr)
  c.height = Math.round(h * dpr)
  const ctx = c.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  const { dist, elev } = props.profile
  if (dist.length < 2 || w === 0) return

  if (zoom.value > 1) follow()
  const a = zoom.value > 1 ? offset.value : 0
  const b = a + span.value
  // the visible points plus one on each side so the curve reaches the edges, thinned to about one per pixel
  let i0 = dist.findIndex((d) => d >= a)
  i0 = Math.max(0, i0 - 1)
  let i1 = dist.findIndex((d) => d > b)
  i1 = i1 < 0 ? dist.length - 1 : i1
  const every = Math.max(1, Math.floor((i1 - i0) / w))
  const idx: number[] = []
  for (let i = i0; i < i1; i += every) idx.push(i)
  idx.push(i1)

  let lo = Infinity
  let hi = -Infinity
  for (const i of idx) {
    lo = Math.min(lo, elev[i]!)
    hi = Math.max(hi, elev[i]!)
  }
  const range = Math.max(hi - lo, 10)
  const x = (d: number) => ((d - a) / (b - a)) * w
  const y = (e: number) => h - ((e - lo) / range) * h * 0.8 - h * 0.1

  // one filled band per run of the same load colour
  const { grade } = props.profile
  const bandColor = (k: number) => {
    const [i, j] = [idx[k]!, Math.max(idx[k + 1]!, idx[k]! + 1)]
    let sum = 0
    for (let n = i; n < j; n++) sum += grade[n]!
    return loadColor(Math.round(props.load(sum / (j - i)) * LOAD_STEPS) / LOAD_STEPS)
  }
  let k = 0
  while (k < idx.length - 1) {
    const color = bandColor(k)
    ctx.beginPath()
    ctx.moveTo(x(dist[idx[k]!]!), h)
    ctx.lineTo(x(dist[idx[k]!]!), y(elev[idx[k]!]!))
    while (k < idx.length - 1 && bandColor(k) === color) {
      k++
      ctx.lineTo(x(dist[idx[k]!]!), y(elev[idx[k]!]!))
    }
    ctx.lineTo(x(dist[idx[k]!]!), h)
    ctx.closePath()
    ctx.fillStyle = color
    ctx.globalAlpha = 0.45
    ctx.fill()
  }
  ctx.globalAlpha = 1

  ctx.strokeStyle = '#fff'
  ctx.lineWidth = 2
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.beginPath()
  idx.forEach((i, n) => (n ? ctx.lineTo(x(dist[i]!), y(elev[i]!)) : ctx.moveTo(x(dist[i]!), y(elev[i]!))))
  ctx.stroke()

  const cx = x(props.dist)
  // the ridden part fades out: only what is drawn gets lighter, the video behind stays as it is
  ctx.globalCompositeOperation = 'destination-out'
  ctx.fillStyle = `rgba(0, 0, 0, ${RIDDEN_FADE})`
  ctx.fillRect(0, 0, Math.max(0, Math.min(w, cx)), h)
  ctx.globalCompositeOperation = 'source-over'

  ctx.font = LABEL
  ctx.fillStyle = '#fff'
  ctx.shadowColor = 'rgba(0, 0, 0, 0.9)'
  ctx.shadowBlur = 3
  // height range on the left, the shown stretch top right
  ctx.textBaseline = 'middle'
  ctx.fillText(`${Math.round(hi)} m`, 6, y(hi))
  ctx.fillText(`${Math.round(lo)} m`, 6, y(lo))
  ctx.textBaseline = 'top'
  ctx.textAlign = 'right'
  ctx.fillText(`${fmtKm(a, 1).replace(' km', '')} – ${fmtKm(b, 1)}`, w - 6, 6)

  // the rider: a line from the dot down to the bottom, the km and the dot on the curve
  if (props.dist < a || props.dist > b) return
  let r = dist.findIndex((d) => d >= props.dist)
  r = r < 0 ? dist.length - 1 : r
  const prev = Math.max(0, r - 1)
  const t = dist[r]! > dist[prev]! ? (props.dist - dist[prev]!) / (dist[r]! - dist[prev]!) : 0
  const cy = y(elev[prev]! + (elev[r]! - elev[prev]!) * t)
  // the km above the dot, kept inside the chart; beside the dot when there is no room above
  const label = fmtKm(props.dist, 1)
  const half = ctx.measureText(label).width / 2
  if (cy - 26 >= 0) {
    ctx.textAlign = 'center'
    ctx.textBaseline = 'bottom'
    ctx.fillText(label, Math.min(w - 6 - half, Math.max(6 + half, cx)), cy - 12)
  } else {
    const left = cx > w - 90
    ctx.textAlign = left ? 'right' : 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, cx + (left ? -14 : 14), cy)
  }
  ctx.shadowBlur = 0
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(cx, cy) // from the dot down only
  ctx.lineTo(cx, h)
  ctx.stroke()
  ctx.beginPath()
  ctx.arc(cx, cy, 8, 0, Math.PI * 2)
  ctx.fillStyle = '#fff'
  ctx.fill()
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.7)'
  ctx.lineWidth = 3
  ctx.stroke()
}

function onClick(ev: MouseEvent) {
  const r = (ev.currentTarget as HTMLElement).getBoundingClientRect()
  const a = zoom.value > 1 ? offset.value : 0
  emit('seek', a + ((ev.clientX - r.left) / r.width) * span.value)
}

let frame = 0
const redraw = () => {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(draw)
}
watch(() => [props.profile, props.dist, props.load, zoom.value, offset.value], redraw)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(redraw)
  observer.observe(canvas.value!)
  redraw()
})
onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(frame)
})
</script>

<template>
  <div class="track">
    <canvas ref="canvas" @click="onClick" />
    <div class="controls" :class="{ hidden: !props.controls }">
      <button type="button" aria-label="Posunout zpět" :disabled="zoom === 1" @click="scroll(-1)">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.5 5v14L6.5 12Z" /></svg>
      </button>
      <button type="button" aria-label="Oddálit" :disabled="zoom === 1" @click="zoomBy(1 / ZOOM_STEP)">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 11h14v2H5Z" /></svg>
      </button>
      <span class="num">{{ Math.round(zoom * 100) }} %</span>
      <button type="button" aria-label="Přiblížit" :disabled="zoom >= ZOOM_MAX" @click="zoomBy(ZOOM_STEP)">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6Z" /></svg>
      </button>
      <button type="button" aria-label="Posunout vpřed" :disabled="zoom === 1" @click="scroll(1)">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 5v14l11-7Z" /></svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.track {
  position: relative;
  /* the ride screen sets it: a fixed share of the screen, or the black bar under a whole video */
  height: var(--track-h, max(15vh, 100px));
}
canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: pointer;
}
/* sized for a finger on a tablet; the same dark glass discs as the ride screen's playback controls */
.controls {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: opacity 0.3s;
}
.controls.hidden {
  opacity: 0;
  pointer-events: none;
}
.controls.hidden * {
  pointer-events: none;
}
.controls span {
  min-width: 52px;
  text-align: center;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
}
/* svg icons instead of text glyphs: − and + sit off centre in most fonts */
button {
  display: grid;
  place-items: center;
  padding: 0;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.3);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  color: #fff;
  font: inherit;
  font-size: 20px;
  cursor: pointer;
  transition:
    transform 0.12s,
    background 0.12s;
}
button svg {
  width: 22px;
  height: 22px;
  fill: currentColor;
}
button:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.4);
}
button:active:not(:disabled) {
  transform: scale(0.94);
  background: rgba(0, 0, 0, 0.5);
}
button:disabled {
  opacity: 0.35;
  cursor: default;
}
</style>
