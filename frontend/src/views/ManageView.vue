<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { addVideo, fetchManagedVideos, fetchSession, FormError, processVideo } from '@/api'
import type { FormErrors, ManagedVideo, Session, Verdict } from '@/types/manage'

// fast while the worker reports progress, slow otherwise (new videos from the admin still show up)
const POLL_ACTIVE_MS = 5000
const POLL_IDLE_MS = 30000
const ACTIVE = ['queued', 'processing']
const VERDICT_LABEL: Record<Verdict, string> = { good: '✓ dobré', warn: '⚠ podezřelé', bad: '✗ špatné' }
const SOURCE_HINT: Record<string, string> = {
  overlay: 'video má v obraze cyklopočítač (km, rychlost, výška nebo sklon)',
  gpx: 'máš GPX trasy; dá i mapu a 3D průlet',
  video: 'nic z toho; nepřesné, na ARM workeru nepoběží',
}
const LOGIN_URL = '/admin/login/?next=/manage'

const session = ref<Session | null>(null)
const videos = ref<ManagedVideo[] | null>(null)
const loadError = ref<string | null>(null)
const busy = reactive<Record<number, boolean>>({})
const actionError = ref<string | null>(null)

const form = reactive({ url: '', dataUrl: '', gradeSource: 'overlay', process: true })
const gpxInput = ref<HTMLInputElement | null>(null)
const errors = ref<FormErrors>({})
const saving = ref(false)
const added = ref<string | null>(null)

const anyActive = computed(() => videos.value?.some((v) => ACTIVE.includes(v.status)) ?? false)
let timer: ReturnType<typeof setTimeout> | undefined

async function refresh() {
  clearTimeout(timer)
  try {
    videos.value = await fetchManagedVideos()
    loadError.value = null
  } catch (e) {
    loadError.value = (e as Error).message
  }
  timer = setTimeout(refresh, anyActive.value ? POLL_ACTIVE_MS : POLL_IDLE_MS)
}

onMounted(async () => {
  document.title = 'OpenRide – správa videí'
  try {
    session.value = await fetchSession()
  } catch (e) {
    loadError.value = (e as Error).message
    return
  }
  if (session.value.is_staff) await refresh()
})
onBeforeUnmount(() => clearTimeout(timer))

function fieldErrors(...names: string[]): string[] {
  return names.flatMap((n) => errors.value[n] ?? [])
}

async function submit() {
  saving.value = true
  errors.value = {}
  added.value = null
  const data = new FormData()
  data.append('source_id', form.url)
  data.append('data_source_id', form.dataUrl)
  data.append('grade_source', form.gradeSource)
  data.append('process', String(form.process))
  const gpx = gpxInput.value?.files?.[0]
  if (gpx) data.append('gpx', gpx)
  try {
    const video = await addVideo(data)
    added.value = video.title
    form.url = form.dataUrl = ''
    if (gpxInput.value) gpxInput.value.value = ''
    await refresh()
  } catch (e) {
    errors.value = e instanceof FormError ? e.errors : { __all__: [(e as Error).message] }
  } finally {
    saving.value = false
  }
}

async function process(v: ManagedVideo) {
  busy[v.id] = true
  actionError.value = null
  try {
    await processVideo(v.id)
    await refresh()
  } catch (e) {
    actionError.value = `${v.title}: ${(e as Error).message}`
  } finally {
    busy[v.id] = false
  }
}

const pct = (v: ManagedVideo) => Math.round(v.progress?.pct ?? 0)
</script>

<template>
  <main class="manage">
    <header>
      <h1>Správa videí</h1>
      <nav>
        <RouterLink :to="{ name: 'routes' }">trasy</RouterLink>
        <a href="/admin/">admin</a>
        <span v-if="session?.user" class="who">{{ session.user }}</span>
      </nav>
    </header>

    <p v-if="loadError" class="msg err">Nepodařilo se načíst: {{ loadError }}</p>
    <p v-else-if="!session" class="msg">Načítám…</p>
    <p v-else-if="!session.is_staff" class="msg">
      Správa je jen pro správce. <a :href="LOGIN_URL">Přihlásit se</a>
    </p>

    <template v-else>
      <section class="card">
        <h2>Přidat video</h2>
        <form class="add" @submit.prevent="submit">
          <label class="field wide">
            <span class="k">URL videa (přehrává se)</span>
            <input
              v-model.trim="form.url"
              type="text"
              required
              placeholder="https://www.youtube.com/watch?v=…"
              autocomplete="off"
            />
            <small v-for="m in fieldErrors('source_id', 'source')" :key="m" class="err">{{ m }}</small>
          </label>
          <label class="field wide">
            <span class="k">URL videa pro zpracování <em>volitelné</em></span>
            <input
              v-model.trim="form.dataUrl"
              type="text"
              placeholder="jiná verze stejné jízdy, např. s overlayem cyklopočítače"
              autocomplete="off"
            />
            <small v-for="m in fieldErrors('data_source_id')" :key="m" class="err">{{ m }}</small>
          </label>

          <fieldset class="field wide">
            <legend class="k">Výpočet sklonu</legend>
            <div class="sources">
              <label
                v-for="s in session.grade_sources"
                :key="s.value"
                class="source"
                :class="{ on: form.gradeSource === s.value }"
              >
                <input v-model="form.gradeSource" type="radio" name="grade_source" :value="s.value" />
                <span>
                  <b>{{ s.label }}</b>
                  <small>{{ SOURCE_HINT[s.value] }}</small>
                </span>
              </label>
            </div>
            <small v-for="m in fieldErrors('grade_source')" :key="m" class="err">{{ m }}</small>
          </fieldset>

          <label class="field">
            <span class="k"
              >GPX <em>{{ form.gradeSource === 'gpx' ? 'povinné' : 'volitelné' }}</em></span
            >
            <input ref="gpxInput" type="file" accept=".gpx,application/gpx+xml" />
            <small v-for="m in fieldErrors('gpx')" :key="m" class="err">{{ m }}</small>
          </label>

          <div class="submit">
            <label class="check"><input v-model="form.process" type="checkbox" /> hned zpracovat</label>
            <button type="submit" :disabled="saving || !form.url">
              {{ saving ? 'Ukládám…' : 'Přidat' }}
            </button>
          </div>
          <p v-for="m in fieldErrors('__all__')" :key="m" class="err wide">{{ m }}</p>
          <p v-if="added" class="ok wide">Přidáno: {{ added }}</p>
        </form>
      </section>

      <section>
        <h2>Videa</h2>
        <p v-if="actionError" class="msg err">{{ actionError }}</p>
        <p v-if="!videos" class="msg">Načítám…</p>
        <p v-else-if="!videos.length" class="msg">Zatím žádná videa.</p>
        <ul v-else class="videos">
          <li v-for="v in videos" :key="v.id" class="video card" :class="v.status">
            <img :src="`https://i.ytimg.com/vi/${v.source_id}/mqdefault.jpg`" alt="" loading="lazy" />
            <div class="info">
              <div class="title">{{ v.title }}</div>
              <div class="chips">
                <span>{{ v.grade_source_label }}</span>
                <span v-if="v.has_gpx">GPX</span>
                <span v-if="v.data_source_id">2 verze videa</span>
              </div>
              <div class="state">
                <span class="status">{{ v.status_label }}</span>
                <span v-if="v.status !== 'new'" class="detail">{{ v.state }}</span>
                <span v-if="v.verdict && v.status === 'ready'" class="verdict" :class="v.verdict">
                  {{ VERDICT_LABEL[v.verdict] }}
                </span>
              </div>
              <div
                v-if="v.status === 'processing' && v.progress"
                class="bar"
                role="progressbar"
                :aria-valuenow="pct(v)"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-label="v.progress.step"
              >
                <div :style="{ width: `${pct(v)}%` }"></div>
              </div>
              <p v-if="v.status === 'failed' && v.error" class="err">{{ v.error }}</p>
              <details v-if="v.quality.length">
                <summary>kvalita výsledku</summary>
                <table>
                  <tr v-for="q in v.quality" :key="q.label">
                    <td>{{ q.label }}</td>
                    <td>{{ q.value }}</td>
                    <td :class="['verdict', q.verdict]">{{ q.verdict ? VERDICT_LABEL[q.verdict] : '' }}</td>
                  </tr>
                </table>
              </details>
            </div>
            <div class="actions">
              <button type="button" :disabled="busy[v.id] || ACTIVE.includes(v.status)" @click="process(v)">
                {{ v.status === 'new' ? 'Zpracovat' : 'Zpracovat znovu' }}
              </button>
              <RouterLink v-if="v.status === 'ready'" :to="{ name: 'ride', params: { id: v.route_id } }"
                >trenažér</RouterLink
              >
              <RouterLink v-if="v.status === 'ready'" :to="{ name: 'check', params: { id: v.route_id } }"
                >kontrola</RouterLink
              >
              <a :href="v.admin_url">v adminu</a>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </main>
</template>

<style scoped>
.manage {
  --good: #2f855a;
  --warn: #b7791f;
  --bad: #c53030;
  max-width: 980px;
  margin: 0 auto;
  padding: 16px;
}
@media (prefers-color-scheme: dark) {
  .manage {
    --good: #48bb78;
    --warn: #d69e2e;
    --bad: #f56565;
  }
}
header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
h1 {
  font-size: 20px;
  margin: 0;
}
h2 {
  font-size: 16px;
  margin: 0 0 12px;
}
nav {
  display: flex;
  gap: 14px;
  font-size: 14px;
}
.who {
  color: var(--muted);
}
.msg {
  color: var(--text-2);
}
.err {
  color: var(--bad);
}
.ok {
  color: var(--good);
}
section {
  margin-bottom: 24px;
}
.card {
  background: var(--surface-2);
  border-radius: 10px;
  padding: 14px 16px;
}

.add {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 16px;
}
.wide {
  grid-column: 1 / -1;
  margin: 0;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 0;
  padding: 0;
  min-width: 0;
}
.k em {
  font-style: normal;
  text-transform: none;
  letter-spacing: 0;
  color: var(--muted);
}
input[type='text'] {
  font: inherit;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg);
  color: var(--text);
  width: 100%;
}
.sources {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px;
}
.source {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  background: var(--bg);
}
.source.on {
  border-color: var(--accent);
}
.source span {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.source small {
  color: var(--text-2);
  font-size: 12px;
}
.submit {
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  gap: 16px;
}
.check {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 14px;
}
button {
  font: inherit;
  font-weight: 600;
  padding: 8px 16px;
  border-radius: 6px;
  border: 0;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
button:disabled {
  opacity: 0.45;
  cursor: default;
}

.videos {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.video {
  display: grid;
  grid-template-columns: 160px 1fr auto;
  gap: 14px;
  align-items: start;
}
.video img {
  width: 160px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
  border-radius: 6px;
  background: var(--line);
  display: block;
}
.info {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.title {
  font-weight: 600;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}
.chips span {
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 1px 6px;
  color: var(--text-2);
}
.state {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 14px;
}
.status {
  font-weight: 600;
}
.detail {
  color: var(--text-2);
}
.verdict {
  font-weight: 600;
  white-space: nowrap;
}
.verdict.good {
  color: var(--good);
}
.verdict.warn {
  color: var(--warn);
}
.verdict.bad {
  color: var(--bad);
}
.bar {
  height: 6px;
  border-radius: 3px;
  background: var(--line);
  overflow: hidden;
}
.bar div {
  height: 100%;
  background: var(--accent);
  transition: width 0.5s;
}
details {
  font-size: 13px;
}
summary {
  cursor: pointer;
  color: var(--text-2);
}
table {
  border-collapse: collapse;
  margin-top: 6px;
}
td {
  padding: 2px 14px 2px 0;
  vertical-align: top;
}
.actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  font-size: 14px;
}

@media (max-width: 640px) {
  .add {
    grid-template-columns: 1fr;
  }
  .video {
    grid-template-columns: 96px 1fr;
  }
  .video img {
    width: 96px;
  }
  .actions {
    grid-column: 1 / -1;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
  }
}
</style>
