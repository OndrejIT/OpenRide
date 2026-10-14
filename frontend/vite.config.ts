import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { loadEnv, type Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

const mockDir = fileURLToPath(new URL('./mock', import.meta.url))

// Serves frontend/mock/*.json as the read-only API while the Django backend is not running.
function mockApi(): Plugin {
  return {
    name: 'openride-mock-api',
    configureServer(server) {
      server.middlewares.use('/api', (req, res) => {
        const path = (req.url ?? '').split('?')[0]
        const m = /^\/routes\/(?:(\d+)\/)?$/.exec(path ?? '')
        const file = m ? (m[1] ? `${mockDir}/routes/${m[1]}.json` : `${mockDir}/routes.json`) : null
        res.setHeader('Content-Type', 'application/json')
        if (!file || !existsSync(file)) {
          res.statusCode = 404
          res.end('{"detail":"Not found."}')
          return
        }
        res.end(readFileSync(file))
      })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env }
  const mock = env.VITE_MOCK === '1'
  return {
    base: '/',
    plugins: [vue(), mock ? mockApi() : null],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      watch: env.VITE_WATCH_POLL === '1' ? { usePolling: true, interval: 300 } : undefined,
      proxy: mock
        ? undefined
        : Object.fromEntries(
            // /admin and its /static: logging in on the dev server's origin gives the dashboard its session
            ['/api', '/admin', '/static'].map((p) => [
              p,
              { target: env.VITE_API_PROXY || 'http://localhost:8000', changeOrigin: true },
            ]),
          ),
    },
    build: { outDir: 'dist' },
    test: { include: ['src/**/*.test.ts'], environment: 'node' },
  }
})
