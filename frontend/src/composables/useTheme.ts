import { ref, watch } from 'vue'

const STORAGE_KEY = 'openride.theme'

export type Theme = 'auto' | 'dark' | 'light'
export const THEMES: { value: Theme; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'dark', label: 'Tmavý' },
  { value: 'light', label: 'Světlý' },
]

function load(): Theme {
  try {
    const t = localStorage.getItem(STORAGE_KEY)
    return t === 'dark' || t === 'light' ? t : 'auto'
  } catch {
    return 'auto'
  }
}

// auto = no attribute: the stylesheet follows the system setting
function apply(t: Theme) {
  if (t === 'auto') delete document.documentElement.dataset.theme
  else document.documentElement.dataset.theme = t
}

const theme = ref<Theme>(load())
apply(theme.value)
watch(theme, (t) => {
  apply(t)
  try {
    localStorage.setItem(STORAGE_KEY, t)
  } catch {
    // blocked storage: back to auto on reload
  }
})

/** Colour theme of the whole app; applied on import so the first paint already has it. */
export function useTheme() {
  return theme
}
