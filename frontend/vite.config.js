import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../app/static/react",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:5050",
        changeOrigin: true,
      },
      "/auth": {
        target: "http://localhost:5050",
        changeOrigin: true,
      },
      '/socket.io': {
        target: 'http://localhost:5050',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
