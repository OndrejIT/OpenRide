<script setup lang="ts">
import { ref, watch } from 'vue'
import { useResize } from '@/composables/useResize'
import { gradeColor, setupCanvas, tokenReader } from '@/lib/draw'
import { floorIndex, fmtTime } from '@/lib/ride'

// Per-second series of the check page: moving window (elev / grade) or the whole video (overview).
const props = defineProps<{
  t: number[]
  elev: number[]
  grade: number[]
  time: number
  /** half-width of the moving window, s */
  win: number
  mode: 'elev' | 'grade' | 'overview'
  height: number
}>()
const emit = defineEmits<{ seek: [time: number] }>()

const PAD = { l: 48, r: 10, t: 10, b: 22 }
const TICKS = [15, 30, 60, 120, 300, 600, 900, 1800, 3600]
const canvas = ref<HTMLCanvasElement>()
const minus = (s: string) => s.replace('-', '−')

function range(): [number, number] {
  const end = props.t[props.t.length - 1] ?? 0
  return props.mode === 'overview' ? [0, end || 1] : [props.time - props.win, props.time + props.win]
}

function draw() {
  const c = canvas.value
  if (!c || !c.clientWidth || props.t.length < 2) return
  const { ctx, w, h } = setupCanvas(c, props.height)
  const token = tokenReader(c)
  const [t0, t1] = range()
  const i0 = floorIndex(props.t, t0)
  const i1 = Math.min(props.t.length - 1, floorIndex(props.t, t1) + 1)
  const x = (s: number) => PAD.l + ((s - t0) / (t1 - t0)) * (w - PAD.l - PAD.r)
  const base = h - PAD.b
  ctx.font = '11px system-ui'
  ctx.lineWidth = 1

  // time axis
  const tick = TICKS.find((s) => (t1 - t0) / s <= 10) ?? 3600
  ctx.textAlign = 'center'
  for (let s = Math.max(0, Math.ceil(t0 / tick) * tick); s <= t1; s += tick) {
    ctx.strokeStyle = token('--grid')
    ctx.beginPath()
    ctx.moveTo(x(s) + 0.5, PAD.t)
    ctx.lineTo(x(s) + 0.5, base)
    ctx.stroke()
    ctx.fillStyle = token('--text-2')
    ctx.fillText(fmtTime(s), x(s), h - 6)
  }

  const series = props.mode === 'grade' ? props.grade : props.elev
  let lo = Infinity
  let hi = -Infinity
  for (let i = i0; i <= i1; i++) {
    lo = Math.min(lo, series[i]!)
    hi = Math.max(hi, series[i]!)
  }
  let y: (v: number) => number
  ctx.textAlign = 'right'
  if (props.mode === 'grade') {
    const lim = Math.ceil(Math.max(4, Math.abs(lo), Math.abs(hi)) / 2) * 2
    y = (g) => PAD.t + (1 - (g + lim) / (2 * lim)) * (base - PAD.t)
    for (let g = -lim; g <= lim; g += lim > 8 ? 4 : 2) {
      ctx.strokeStyle = token(g === 0 ? '--muted' : '--grid')
      ctx.beginPath()
      ctx.moveTo(PAD.l, y(g) + 0.5)
      ctx.lineTo(w - PAD.r, y(g) + 0.5)
      ctx.stroke()
      ctx.fillStyle = token('--text-2')
      ctx.fillText(minus(`${g > 0 ? '+' : ''}${g} %`), PAD.l - 6, y(g) + 4)
    }
  } else {
    const mid = (lo + hi) / 2
    const span = Math.max(hi - lo, 20) * 1.15
    const [a, b] = [mid - span / 2, mid + span / 2]
    y = (e) => PAD.t + (1 - (e - a) / (b - a)) * (base - PAD.t)
    const est = span > 400 ? 100 : span > 120 ? 50 : span > 50 ? 20 : span > 25 ? 10 : 5
    for (let e = Math.ceil(a / est) * est; e <= b; e += est) {
      ctx.strokeStyle = token('--grid')
      ctx.beginPath()
      ctx.moveTo(PAD.l, y(e) + 0.5)
      ctx.lineTo(w - PAD.r, y(e) + 0.5)
      ctx.stroke()
      ctx.fillStyle = token('--text-2')
      ctx.fillText(minus(`${e} m`), PAD.l - 6, y(e) + 4)
    }
  }

  ctx.save()
  ctx.beginPath()
  ctx.rect(PAD.l, 0, w - PAD.l - PAD.r, h)
  ctx.clip()
  if (props.mode !== 'grade') {
    for (let i = i0; i < i1; i++) {
      ctx.fillStyle = gradeColor(token, props.grade[i]!)
      ctx.beginPath()
      ctx.moveTo(x(props.t[i]!), base)
      ctx.lineTo(x(props.t[i]!), y(props.elev[i]!))
      ctx.lineTo(x(props.t[i + 1]!) + 0.6, y(props.elev[i + 1]!))
      ctx.lineTo(x(props.t[i + 1]!) + 0.6, base)
      ctx.fill()
    }
  }
  ctx.strokeStyle = token('--text-2')
  ctx.lineWidth = props.mode === 'grade' ? 2 : 1.5
  ctx.lineJoin = 'round'
  ctx.beginPath()
  for (let i = i0; i <= i1; i++) {
    if (i === i0) ctx.moveTo(x(props.t[i]!), y(series[i]!))
    else ctx.lineTo(x(props.t[i]!), y(series[i]!))
  }
  ctx.stroke()
  if (props.mode === 'overview') {
    const a = x(Math.max(0, props.time - props.win))
    ctx.fillStyle = token('--shade')
    ctx.fillRect(a, 0, x(Math.min(t1, props.time + props.win)) - a, base)
  }
  ctx.restore()

  ctx.strokeStyle = token('--cursor')
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(x(props.time), PAD.t)
  ctx.lineTo(x(props.time), base)
  ctx.stroke()
}

function onClick(ev: MouseEvent) {
  const c = canvas.value
  if (!c) return
  const r = c.getBoundingClientRect()
  const [t0, t1] = range()
  const s = t0 + ((ev.clientX - r.left - PAD.l) / (r.width - PAD.l - PAD.r)) * (t1 - t0)
  const end = props.t[props.t.length - 1] ?? 0
  if (s >= 0 && s <= end) emit('seek', s)
}

useResize(canvas, draw)
watch(() => [props.time, props.win, props.t, props.mode], draw)
</script>

<template>
  <canvas ref="canvas" class="time-chart" @click="onClick" />
</template>

<style scoped>
.time-chart {
  display: block;
  width: 100%;
  cursor: pointer;
}
</style>
