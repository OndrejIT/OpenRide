<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { THEMES, useTheme } from '@/composables/useTheme'

// Wrench menu with everything besides riding: colour theme, adding videos, past rides, trainer setup, Django admin.
const open = ref(false)
const theme = useTheme()
const root = ref<HTMLElement>()

function onDocClick(e: MouseEvent) {
  if (open.value && !root.value?.contains(e.target as Node)) open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="settings">
    <button
      type="button"
      class="wrench"
      aria-label="Nastavení"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="open = !open"
    >
      <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
        <path
          fill="currentColor"
          d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4Z"
        />
      </svg>
    </button>
    <nav v-if="open" class="menu" role="menu" @click="open = false">
      <div class="theme" role="group" aria-label="Vzhled" @click.stop>
        <span>Vzhled</span>
        <div class="seg">
          <button
            v-for="t in THEMES"
            :key="t.value"
            type="button"
            :aria-pressed="theme === t.value"
            @click="theme = t.value"
          >
            {{ t.label }}
          </button>
        </div>
      </div>
      <RouterLink :to="{ name: 'manage' }" role="menuitem">
        <b>Přidat / spravovat videa</b>
        <small>URL z YouTube, zpracování, stav</small>
      </RouterLink>
      <RouterLink :to="{ name: 'rides' }" role="menuitem">
        <b>Odjeté jízdy</b>
        <small>historie, výkon, kadence, tep</small>
      </RouterLink>
      <RouterLink :to="{ name: 'trainer' }" role="menuitem">
        <b>Trenažér</b>
        <small>most ESP32, Kettler, odpor</small>
      </RouterLink>
      <a href="/admin/" role="menuitem">
        <b>Admin</b>
        <small>Django administrace</small>
      </a>
    </nav>
  </div>
</template>

<style scoped>
.settings {
  position: relative;
}
.wrench {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
}
.wrench:hover,
.wrench[aria-expanded='true'] {
  color: var(--text);
}
.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  z-index: 1000;
  min-width: 240px;
  display: flex;
  flex-direction: column;
  padding: 6px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--bg);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
}
.menu a {
  display: flex;
  flex-direction: column;
  padding: 8px 10px;
  border-radius: 6px;
  text-decoration: none;
}
.menu a:hover,
.menu a:focus-visible {
  background: var(--surface-2);
}
.theme {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 10px 10px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
  color: var(--text-2);
}
.seg {
  display: flex;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.seg button {
  font: inherit;
  font-size: 13px;
  padding: 5px 10px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}
.seg button + button {
  border-left: 1px solid var(--line);
}
.seg button[aria-pressed='true'] {
  background: var(--surface-2);
  color: var(--text);
  font-weight: 600;
}
.menu small {
  color: var(--text-2);
  font-size: 12px;
}
</style>
