<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { loadYouTubeApi } from '@/lib/youtube'

const props = withDefaults(defineProps<{ videoId: string; controls?: boolean }>(), { controls: false })
const emit = defineEmits<{ playing: [value: boolean]; error: [message: string] }>()

const host = ref<HTMLDivElement>()
let player: YT.Player | null = null
let ready = false

onMounted(async () => {
  try {
    await loadYouTubeApi()
  } catch (e) {
    emit('error', (e as Error).message)
    return
  }
  if (!host.value) return
  // YT replaces its target element, so give it one Vue does not track
  const target = document.createElement('div')
  host.value.append(target)
  player = new YT.Player(target, {
    videoId: props.videoId,
    playerVars: props.controls
      ? { rel: 0, playsinline: 1 }
      : { controls: 0, rel: 0, playsinline: 1, disablekb: 1, iv_load_policy: 3 },
    events: {
      onReady: () => (ready = true),
      onStateChange: (e) => emit('playing', e.data === YT.PlayerState.PLAYING),
      onError: (e) => emit('error', `Chyba přehrávače YouTube (${e.data})`),
    },
  })
})

onBeforeUnmount(() => player?.destroy())

defineExpose({
  currentTime: (): number | null => (ready && player ? player.getCurrentTime() : null),
  state: (): YT.PlayerState | null => (ready && player ? player.getPlayerState() : null),
  seekTo: (s: number) => ready && player?.seekTo(s, true),
  play: () => ready && player?.playVideo(),
  pause: () => ready && player?.pauseVideo(),
})
</script>

<template>
  <div ref="host" class="yt" :class="{ passive: !controls }" />
</template>

<style scoped>
.yt {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
}
.yt :deep(iframe) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
}
/* HUD owns the controls; keep clicks off the iframe */
.passive :deep(iframe) {
  pointer-events: none;
}
</style>
