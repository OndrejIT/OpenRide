<script setup lang="ts">
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { LatLon } from '@/types/api'
import { tokenReader } from '@/lib/draw'

const props = withDefaults(
  defineProps<{
    segment: LatLon[]
    position?: LatLon | null
    interactive?: boolean
    attribution?: boolean
  }>(),
  { position: null, interactive: true, attribution: false },
)
const emit = defineEmits<{ pick: [lat: number, lon: number] }>()

const box = ref<HTMLDivElement>()
let map: L.Map | null = null
let marker: L.CircleMarker | null = null
let ro: ResizeObserver | null = null

function placeMarker(p: LatLon | null) {
  if (!map) return
  if (!p) {
    marker?.remove()
    marker = null
  } else if (marker) marker.setLatLng(p)
  else
    marker = L.circleMarker(p, {
      radius: 6,
      color: '#fff',
      weight: 2,
      fillColor: '#000',
      fillOpacity: 1,
    }).addTo(map)
}

onMounted(() => {
  if (!box.value) return
  const token = tokenReader(box.value)
  map = L.map(box.value, {
    zoomControl: props.interactive,
    attributionControl: props.attribution,
    dragging: props.interactive,
    scrollWheelZoom: props.interactive,
    doubleClickZoom: props.interactive,
    boxZoom: props.interactive,
    touchZoom: props.interactive,
    keyboard: false,
  })
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '© OpenStreetMap',
  }).addTo(map)
  const line = L.polyline(props.segment, { color: token('--accent'), weight: 4 }).addTo(map)
  map.fitBounds(line.getBounds(), { padding: [10, 10] })
  if (props.interactive)
    line.on('click', (e: L.LeafletMouseEvent) => emit('pick', e.latlng.lat, e.latlng.lng))
  ro = new ResizeObserver(() => map?.invalidateSize())
  ro.observe(box.value)
  placeMarker(props.position)
})

watch(() => props.position, placeMarker)

onBeforeUnmount(() => {
  ro?.disconnect()
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="box" class="route-map" />
</template>

<style scoped>
.route-map {
  width: 100%;
  height: 100%;
  background: var(--surface-2);
}
</style>
