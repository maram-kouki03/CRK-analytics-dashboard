import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Le client API appelle des URLs relatives (/api/...) par défaut, et ce proxy les
// renvoie vers crk-backend en dev. On évite ainsi CORS et toute URL codée en dur.
// CRK_BACKEND_URL (ou VITE_API_URL) permet de viser un autre hôte.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.CRK_BACKEND_URL || env.VITE_API_URL || 'http://localhost:8080'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
  }
})
