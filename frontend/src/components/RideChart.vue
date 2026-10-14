<script setup lang="ts">
import { computed } from 'vue'
import { fmtTime } from '@/lib/ride'

// One series over ride time; charts of one ride share the x axis and the hovered second (small multiples).
const props = defineProps<{
  title: string
  unit: string
  values: (number | null)[]
  hover: number | null
  /** brake levels change in steps; a sloped line would invent levels in between */
  step?: boolean
  area?: boolean
  digits?: number
}>()
const emit = defineEmits<{ hover: [index: number | null] }>()

const W = 600
const H = 110
const PAD = { l: 40, r: 6, t: 8, b: 18 }
const plotW = W - PAD.l - PAD.r
const plotH = H - PAD.t - PAD.b

const present = computed(() => props.values.filter((v): v is number => v != null))
const yRange = computed(() => {
  const a = present.value
  if (!a.length) return [0, 1] as const
  const lo = Math.min(...a)
  const hi = Math.max(...a)
  const pad = hi === lo ? 1 : (hi - lo) * 0.08
  return [lo - pad, hi + pad] as const
})
const n = computed(() => props.values.length)
const x = (i: number) => PAD.l + (n.value > 1 ? (i / (n.value - 1)) * plotW : 0)
const y = (v: number) => PAD.t + (1 - (v - yRange.value[0]) / (yRange.value[1] - yRange.value[0])) * plotH

/** Path with gaps where the value is missing (trainer not connected). */
const path = computed(() => {
  let d = ''
  let open = false
  props.values.forEach((v, i) => {
    if (v == null) {
      open = false
      return
    }
    if (!open) d += `M${x(i).toFixed(1)},${y(v).toFixed(1)}`
    else if (props.step) d += `H${x(i).toFixed(1)}V${y(v).toFixed(1)}`
    else d += `L${x(i).toFixed(1)},${y(v).toFixed(1)}`
    open = true
  })
  return d
})
const areaPath = computed(() =>
  props.area && present.value.length === n.value && n.value > 1
    ? `${path.value}L${x(n.value - 1).toFixed(1)},${PAD.t + plotH}L${PAD.l},${PAD.t + plotH}Z`
    : '',
)

const fmt = (v: number | null | undefined) =>
  v == null
    ? '–'
    : `${v
        .toFixed(props.digits ?? 0)
        .replace('.', ',')
        .replace('-', '−')} ${props.unit}`
const hoverValue = computed(() => (props.hover == null ? null : props.values[props.hover]))
const ticks = computed(() => {
  const total = n.value
  const step = [60, 300, 600, 900, 1800, 3600].find((s) => total / s <= 6) ?? 3600
  const out: number[] = []
  for (let s = 0; s < total; s += step) out.push(s)
  return out
})

function onMove(e: PointerEvent) {
  const box = (e.currentTarget as SVGElement).getBoundingClientRect()
  const px = ((e.clientX - box.left) / box.width) * W
  const i = Math.round(((px - PAD.l) / plotW) * (n.value - 1))
  emit('hover', i >= 0 && i < n.value ? i : null)
}
</script>

<template>
  <figure class="chart">
    <figcaption>
      <span class="k">{{ title }}</span>
      <span class="num">{{ hover != null ? fmt(hoverValue) : '' }}</span>
    </figcaption>
    <svg
      v-if="present.length"
      :viewBox="`0 0 ${W} ${H}`"
      role="img"
      :aria-label="`${title} v čase`"
      @pointermove="onMove"
      @pointerleave="emit('hover', null)"
    >
      <line class="grid" :x1="PAD.l" :x2="W - PAD.r" :y1="PAD.t" :y2="PAD.t" />
      <line class="grid" :x1="PAD.l" :x2="W - PAD.r" :y1="PAD.t + plotH" :y2="PAD.t + plotH" />
      <text class="label" :x="PAD.l - 4" :y="PAD.t + 4" text-anchor="end">
        {{ fmt(yRange[1]).split(' ')[0] }}
      </text>
      <text class="label" :x="PAD.l - 4" :y="PAD.t + plotH" text-anchor="end">
        {{ fmt(yRange[0]).split(' ')[0] }}
      </text>
      <text v-for="s in ticks" :key="s" class="label" :x="x(s)" :y="H - 4" text-anchor="middle">
        {{ fmtTime(s) }}
      </text>
      <path v-if="areaPath" class="area" :d="areaPath" />
      <path class="line" :d="path" />
      <line
        v-if="hover != null"
        class="cursor"
        :x1="x(hover)"
        :x2="x(hover)"
        :y1="PAD.t"
        :y2="PAD.t + plotH"
      />
      <circle
        v-if="hover != null && hoverValue != null"
        class="dot"
        :cx="x(hover)"
        :cy="y(hoverValue)"
        r="4"
      />
    </svg>
    <p v-else class="empty">bez dat (trenažér nebyl připojený)</p>
  </figure>
</template>

<style scoped>
.chart {
  margin: 0;
}
figcaption {
  display: flex;
  justify-content: space-between;
  margin-bottom: 2px;
}
svg {
  width: 100%;
  height: auto;
  display: block;
  touch-action: none;
}
.grid {
  stroke: var(--grid);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.label {
  fill: var(--muted);
  font-size: 10px;
}
.line {
  fill: none;
  stroke: var(--accent);
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
}
.area {
  fill: var(--shade);
}
.cursor {
  stroke: var(--cursor);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.dot {
  fill: var(--accent);
  stroke: var(--surface-2);
  stroke-width: 2;
}
.empty {
  color: var(--muted);
  font-size: 13px;
  margin: 8px 0 16px;
}
</style>
