import { createApp } from 'vue'
import App from './App.vue'
import { useTheme } from './composables/useTheme'
import { router } from './router'
import './style.css'

useTheme() // before mounting: no flash of the system theme
createApp(App).use(router).mount('#app')
