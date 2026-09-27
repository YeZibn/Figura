import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, '.', 'VITE_')
  return {
    plugins: [react()],
    clearScreen: false,
    server: {
      ...(environment.VITE_DEV_HOST ? { host: environment.VITE_DEV_HOST } : {}),
      port: Number(environment.VITE_DEV_PORT || 1420),
      strictPort: true,
    },
    build: { target: 'es2020' },
  }
})
