<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SettingsMenu from '@/components/SettingsMenu.vue'
import { DEFAULT_LEVELS, useTrainer } from '@/composables/useTrainer'
import { bridge, type BridgeDevice, DEFAULT_BRIDGE_URL, SIM_MAX, SIM_MIN } from '@/lib/trainer'

const trainer = useTrainer()
const { status, error, connected } = trainer
const urlInput = ref(trainer.settings.url)
const actionMsg = ref<string | null>(null)
const busy = ref(false)

const kettler = computed(() => status.value?.kettler)
const data = computed(() => status.value?.data)
const deviceMin = computed(() => data.value?.brake_min ?? 1)
const deviceMax = computed(() => data.value?.brake_max ?? 20)
const lo = computed({
  get: () => trainer.range.value.lo,
  set: (v: number) => trainer.setRange(v, trainer.range.value.hi),
})
const hi = computed({
  get: () => trainer.range.value.hi,
  set: (v: number) => trainer.setRange(trainer.range.value.lo, v),
})
const examples = computed(() => [-5, 0, 5, 10, 15].map((g) => ({ g, level: trainer.levelFor(g) })))

onMounted(() => (document.title = 'OpenRide – trenažér'))

async function run(label: string, action: () => Promise<unknown>) {
  busy.value = true
  actionMsg.value = null
  try {
    await action()
    actionMsg.value = label
    await trainer.refresh()
  } catch (e) {
    actionMsg.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

const base = trainer.base
const scan = () => run('Vyhledávám (~10 s)…', () => bridge.scan(base()))
const select = (d: BridgeDevice) =>
  run(`Vybráno: ${d.name || d.mac}, připojuji…`, () => bridge.selectKettler(base(), d))
const forgetKettler = () => run('Kettler zapomenut.', () => bridge.forgetKettler(base()))
function forgetWifi() {
  if (!confirm('Most zapomene Wi-Fi, restartuje se a začne vysílat nastavovací síť NaKole-xxxx. Pokračovat?'))
    return
  run('Wi-Fi zapomenuta: připoj se k síti NaKole-xxxx a nastav most znovu.', () => bridge.forgetWifi(base()))
}
const resetRange = () => trainer.setRange(null, null)
</script>

<template>
  <main class="trainer-page">
    <header>
      <h1>Trenažér</h1>
      <nav>
        <RouterLink :to="{ name: 'routes' }">trasy</RouterLink>
        <RouterLink :to="{ name: 'manage' }">správa videí</RouterLink>
        <SettingsMenu />
      </nav>
    </header>

    <section class="card">
      <h2>Most (ESP32)</h2>
      <form class="url" @submit.prevent="trainer.setUrl(urlInput)">
        <label>
          <span class="k">Adresa</span>
          <input v-model.trim="urlInput" type="text" :placeholder="DEFAULT_BRIDGE_URL" autocomplete="off" />
        </label>
        <button type="submit">Uložit</button>
      </form>
      <p v-if="error" class="bad">
        {{ error }}. Je most zapnutý a ve stejné síti? Při prvním spuštění vysílá síť <b>NaKole-xxxx</b>;
        připoj se k ní a nastav Wi-Fi.
      </p>
      <p v-else-if="!status" class="muted">Hledám most…</p>
      <dl v-else>
        <dt>Wi-Fi</dt>
        <dd>
          {{ status.wifi.ssid }}
          <span v-if="status.wifi.ip" class="muted">· {{ status.wifi.ip }} · {{ status.wifi.rssi }} dBm</span>
        </dd>
        <dt>Používám</dt>
        <dd>
          {{ trainer.base() }}
          <span v-if="trainer.settings.resolved" class="muted"
            >(adresa nahlášená mostem, rychlejší než jméno)</span
          >
        </dd>
        <dt>Firmware</dt>
        <dd>verze {{ status.version }}</dd>
      </dl>
    </section>

    <template v-if="status">
      <section class="card">
        <h2>Kettler</h2>
        <p v-if="kettler?.mac">
          <b :class="connected ? 'good' : 'bad'">{{ connected ? '● Připojeno' : '○ Nepřipojeno' }}</b>
          {{ kettler.name || data?.device_name }} <span class="muted">{{ kettler.mac }}</span>
        </p>
        <p v-else class="muted">Zatím nevybrán, vyhledej ho.</p>
        <dl v-if="connected" class="live">
          <dt>Kadence</dt>
          <dd class="num">{{ data?.rpm ?? '–' }} rpm</dd>
          <dt>Výkon</dt>
          <dd class="num">{{ data?.power ?? '–' }} W</dd>
          <dt>Tep</dt>
          <dd class="num">{{ data?.pulse ?? '–' }} bpm</dd>
          <dt>Brzda</dt>
          <dd class="num">{{ data?.brake ?? '–' }} / {{ deviceMax }}</dd>
        </dl>
        <div class="buttons">
          <button type="button" :disabled="busy || kettler?.scanning" @click="scan">
            {{ kettler?.scanning ? 'Vyhledávám…' : 'Vyhledat Bluetooth zařízení' }}
          </button>
          <button v-if="kettler?.mac" type="button" class="secondary" :disabled="busy" @click="forgetKettler">
            Zapomenout Kettler
          </button>
        </div>
        <ul v-if="kettler?.devices.length && !kettler.scanning" class="devices">
          <li v-for="d in kettler.devices" :key="d.mac">
            <span>
              <b v-if="d.kettler">{{ d.name }}</b
              ><template v-else>{{ d.name || '(bez názvu)' }}</template>
              <small class="muted">{{ d.mac }} · {{ d.rssi }} dBm</small>
            </span>
            <button type="button" :disabled="busy || d.mac === kettler.mac" @click="select(d)">
              {{ d.mac === kettler.mac ? 'vybráno' : 'Vybrat' }}
            </button>
          </li>
        </ul>
        <p v-if="actionMsg" class="muted">{{ actionMsg }}</p>
      </section>

      <section class="card">
        <h2>Odpor podle sklonu</h2>
        <label class="boost">
          <span class="k">Přitvrdit brzdu</span>
          <input
            type="range"
            :min="-trainer.boostLimit.value"
            :max="trainer.boostLimit.value"
            step="1"
            :value="trainer.settings.boost"
            @input="trainer.setBoost(Number(($event.target as HTMLInputElement).value))"
          />
          <b class="num">{{ trainer.settings.boost > 0 ? '+' : '' }}{{ trainer.settings.boost }}</b>
        </label>
        <p class="muted">
          Přičte se ke každé úrovni, výsledek se ořízne na limity Kettleru. Jde měnit i během jízdy tlačítky −
          / + u zátěže (podržením rychle).
        </p>
        <p class="muted">
          Simulovaný sklon (sklon trasy × obtížnost) od {{ SIM_MIN }} % do +{{ SIM_MAX }} % se rozloží na
          úrovně brzdy v tomto rozsahu.
        </p>
        <div class="range">
          <label>
            <span class="k">Nejnižší úroveň</span>
            <input v-model.number="lo" type="range" :min="deviceMin" :max="deviceMax" step="1" />
            <b class="num">{{ lo }}</b>
          </label>
          <label>
            <span class="k">Nejvyšší úroveň</span>
            <input v-model.number="hi" type="range" :min="deviceMin" :max="deviceMax" step="1" />
            <b class="num">{{ hi }}</b>
          </label>
        </div>
        <p class="examples">
          <span v-for="e in examples" :key="e.g"
            >{{ e.g > 0 ? '+' : '' }}{{ e.g }} % → <b class="num">{{ e.level }}</b></span
          >
        </p>
        <button type="button" class="secondary" @click="resetRange">
          Výchozí ({{ DEFAULT_LEVELS.lo }}–{{ DEFAULT_LEVELS.hi }})
        </button>
      </section>

      <section class="card">
        <h2>Jízda</h2>
        <label class="toggle">
          <input
            type="checkbox"
            :checked="trainer.settings.autoPause"
            @change="trainer.setAutoPause(($event.target as HTMLInputElement).checked)"
          />
          <span>
            Pozastavit video, když nešlapu
            <small class="muted">po 2 s bez otáček; šlapáním se video zase pustí</small>
          </span>
        </label>
      </section>

      <section class="card">
        <h2>Wi-Fi mostu</h2>
        <p class="muted">
          Po zapomenutí se most restartuje a začne vysílat otevřenou síť NaKole-xxxx s nastavením. Totéž udělá
          podržení tlačítka BOOT na ESP32 po dobu 5 s (zapomene i Kettler).
        </p>
        <button type="button" class="danger" :disabled="busy" @click="forgetWifi">Zapomenout Wi-Fi</button>
      </section>
    </template>
  </main>
</template>

<style scoped>
.trainer-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 16px;
}
header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
h1 {
  font-size: 20px;
  margin: 0;
}
h2 {
  font-size: 16px;
  margin: 0 0 10px;
}
nav {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 14px;
}
.card {
  background: var(--surface-2);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.muted {
  color: var(--text-2);
}
.good {
  color: var(--good);
}
.bad {
  color: var(--bad);
}
.url {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.url label {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
input[type='text'] {
  font: inherit;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
}
button {
  font: inherit;
  font-weight: 600;
  padding: 8px 14px;
  border-radius: 6px;
  border: 0;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
button.secondary {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--line);
}
button.danger {
  background: var(--bad);
}
button:disabled {
  opacity: 0.45;
  cursor: default;
}
.buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}
dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 14px;
  margin: 8px 0 0;
}
dt {
  color: var(--text-2);
}
dd {
  margin: 0;
}
.devices {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}
.devices li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-top: 1px solid var(--line);
}
.devices small {
  display: block;
}
.range {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.range label {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px 10px;
  align-items: center;
}
.range .k {
  grid-column: 1 / -1;
}
.boost {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
}
.toggle {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  cursor: pointer;
}
.toggle input {
  margin-top: 4px;
}
.toggle small {
  display: block;
}
.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  font-size: 14px;
}
@media (max-width: 560px) {
  .range {
    grid-template-columns: 1fr;
  }
}
</style>
