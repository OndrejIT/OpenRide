<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Profile } from '@/types/api'
import { useResize } from '@/composables/useResize'
import { gradeColor, setupCanvas, tokenReader } from '@/lib/draw'
import { AHEAD_M, aheadElevations } from '@/lib/ride'

const props = withDefaults(defineProps<{ profile: Profile; dist: number; height?: number }>(), { height: 70 })

const STEP_M = 25
const canvas = ref<HTMLCanvasElement>()

// next 500 m as 25 m columns: height = elevation, colour = grade of the column
function draw() {
  const c = canvas.value
  if (!c || !c.clientWidth) return
  const { ctx, w, h } = setupCanvas(c, props.height)
  const token = tokenReader(c)
  const pts = aheadElevations(props.profile, props.dist, AHEAD_M, STEP_M)
  if (pts.length < 2) return
  const lo = Math.min(...pts)
  const span = Math.max(Math.max(...pts) - lo, 10)
  const base = h - 14
  const y = (e: number) => base - ((e - lo) / span) * (h - 22)
  const colW = w / (AHEAD_M / STEP_M)
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i]!
    const b = pts[i + 1]!
    ctx.fillStyle = gradeColor(token, ((b - a) / STEP_M) * 100)
    ctx.beginPath()
    ctx.moveTo(i * colW, base)
    ctx.lineTo(i * colW, y(a))
    ctx.lineTo((i + 1) * colW - 1, y(b))
    ctx.lineTo((i + 1) * colW - 1, base)
    ctx.fill()
  }
  ctx.fillStyle = token('--text-2')
  ctx.font = '11px system-ui'
  ctx.textAlign = 'left'
  ctx.fillText('teď', 2, h - 2)
  ctx.textAlign = 'center'
  ctx.fillText(`${AHEAD_M / 2} m`, w / 2, h - 2)
  ctx.textAlign = 'right'
  ctx.fillText(`${AHEAD_M} m`, w - 2, h - 2)
}

useResize(canvas, draw)
watch(() => [props.profile, props.dist], draw)
</script>

<template>
  <canvas ref="canvas" class="ahead" />
</template>

<style scoped>
.ahead {
  display: block;
  width: 100%;
}
</style>
