<script setup lang="ts">
import { onBeforeUnmount } from 'vue'

// Button that acts on press and keeps repeating while held: a long way on the brake level without tapping.
const emit = defineEmits<{ step: [] }>()

const DELAY_MS = 400
const EVERY_MS = 120
let timer: ReturnType<typeof setTimeout> | undefined

function start() {
  stop()
  emit('step')
  const again = () => {
    emit('step')
    timer = setTimeout(again, EVERY_MS)
  }
  timer = setTimeout(again, DELAY_MS)
}
function stop() {
  clearTimeout(timer)
  timer = undefined
}
// keyboard activation has no pointer press: one step per Enter / Space
const onClick = (e: MouseEvent) => e.detail === 0 && emit('step')

onBeforeUnmount(stop)
</script>

<template>
  <button
    type="button"
    @pointerdown.prevent="start"
    @pointerup="stop"
    @pointerleave="stop"
    @pointercancel="stop"
    @click="onClick"
  >
    <slot />
  </button>
</template>
