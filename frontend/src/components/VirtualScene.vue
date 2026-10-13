<script setup lang="ts">
import { Map as MapLibreMap, Marker, setWorkerUrl, type StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { LatLon } from '@/types/api'
import { tokenReader } from '@/lib/draw'

// the default worker URL is resolved next to the library file, which does not survive bundling
setWorkerUrl(workerUrl)

const props = defineProps<{ segment: LatLon[]; position: LatLon | null; heading: number | null }>()

const OSM = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TERRARIUM = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
const PITCH = 60
const ZOOM = 16
// share of the remaining heading change applied per update; damps camera swings in tight bends
const TURN_SMOOTHING = 0.12

const box = ref<HTMLDivElement>()
let map: MapLibreMap | null = null
let rider: Marker | null = null
let bearing: number | null = null

function style(accent: string): StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: { type: 'raster', tiles: [OSM], tileSize: 256, maxzoom: 19, attribution: '© OpenStreetMap' },
      dem: {
        type: 'raster-dem',
        tiles: [TERRARIUM],
        tileSize: 256,
        encoding: 'terrarium',
        maxzoom: 15,
        attribution: 'Terrain Tiles (AWS Open Data)',
      },
      route: {
        type: 'geojson',
        data: {
          type: 'Feature',
          properties: {},
          geometry: { type: 'LineString', coordinates: props.segment.map(([lat, lon]) => [lon, lat]) },
        },
      },
    },
    layers: [
      { id: 'osm', type: 'raster', source: 'osm' },
      {
        id: 'route',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': accent, 'line-width': 6, 'line-opacity': 0.85 },
      },
    ],
    terrain: { source: 'dem', exaggeration: 1 },
    sky: {
      'sky-color': '#8fb8de',
      'horizon-color': '#dfe8ee',
      'fog-color': '#dfe8ee',
      'fog-ground-blend': 0.6,
    },
  }
}

/** Camera behind the rider looking along the direction of travel. */
function follow() {
  if (!map || !props.position) return
  const [lat, lon] = props.position
  if (props.heading != null) {
    if (bearing == null) bearing = props.heading
    const diff = ((props.heading - bearing + 540) % 360) - 180
    bearing = (bearing + diff * TURN_SMOOTHING + 360) % 360
  }
  map.jumpTo({ center: [lon, lat], bearing: bearing ?? 0, pitch: PITCH, zoom: ZOOM })
  rider?.setLngLat([lon, lat])
}

onMounted(() => {
  if (!box.value) return
  const start = props.position ?? props.segment[0] ?? [0, 0]
  map = new MapLibreMap({
    container: box.value,
    style: style(tokenReader(box.value)('--accent')),
    center: [start[1], start[0]],
    zoom: ZOOM,
    pitch: PITCH,
    bearing: props.heading ?? 0,
    interactive: false,
    attributionControl: { compact: true },
  })
  const dot = document.createElement('div')
  dot.className = 'rider'
  rider = new Marker({ element: dot }).setLngLat([start[1], start[0]]).addTo(map)
  map.once('load', follow)
})

watch(() => [props.position, props.heading], follow)

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="box" class="virtual-scene" />
</template>

<style scoped>
.virtual-scene {
  position: absolute;
  inset: 0;
  background: #8fb8de;
}
.virtual-scene :deep(.rider) {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #000;
  border: 3px solid #fff;
  box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.35);
}
</style>
