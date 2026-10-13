<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Profile } from '@/types/api'
import { useResize } from '@/composables/useResize'
import { gradeColor, setupCanvas, tokenReader } from '@/lib/draw'
import { fmtKm, routeLength } from '@/lib/ride'

const props = withDefaults(defineProps<{ profile: Profile; dist: number; height?: number }>(), { height: 56 })
const emit = defineEmits<{ seek: [dist: number] }>()

const canvas = ref<HTMLCanvasElement>()
const length = computed(() => routeLength(props.profile))
const pos = computed(
  () => `${(length.value ? Math.min(1, Math.max(0, props.dist / length.value)) : 0) * 100}%`,
)

// static part only; the position overlay is plain CSS so playback does not repaint the canvas
function draw() {
  const c = canvas.value
  if (!c || !c.clientWidth) return
  const { ctx, w, h } = setupCanvas(c, props.height)
  const token = tokenReader(c)
  const { dist, elev, grade } = props.profile
  const lo = Math.min(...elev)
  const hi = Math.max(...elev)
  const x = (d: number) => (d / (length.value || 1)) * w
  const y = (e: number) => 4 + (1 - (e - lo) / (hi - lo || 1)) * (h - 8)
  for (let i = 0; i < dist.length - 1; i++) {
    ctx.fillStyle = gradeColor(token, grade[i]!)
    const top = y(elev[i]!)
    ctx.fillRect(x(dist[i]!), top, x(dist[i + 1]!) - x(dist[i]!) + 0.6, h - top)
  }
}

function onClick(ev: MouseEvent) {
  const r = (ev.currentTarget as HTMLElement).getBoundingClientRect()
  emit('seek', ((ev.clientX - r.left) / r.width) * length.value)
}

useResize(canvas, draw)
watch(() => props.profile, draw)
</script>

<template>
  <div class="route-profile" :title="`Celá trasa ${fmtKm(length, 1)} – klik = skok`" @click="onClick">
    <canvas ref="canvas" />
    <div class="done" :style="{ width: pos }" />
    <div class="cursor" :style="{ left: pos }" />
  </div>
</template>

<style scoped>
.route-profile {
  position: relative;
  cursor: pointer;
}
canvas {
  display: block;
  width: 100%;
}
.done {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: var(--shade);
  pointer-events: none;
}
.cursor {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: var(--cursor);
  pointer-events: none;
}
</style>
