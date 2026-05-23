import { defineConfig } from "vite";
import { sveltekit } from "@sveltejs/kit/vite";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig(async ({ mode }) => ({
  plugins: [sveltekit()],

  // Force browser resolution for Svelte 5 in test mode
  ...(mode === 'test' ? { resolve: { conditions: ['browser', 'svelte', 'node'] } } : {}),

  test: {
    include: ['src/**/*.test.{js,ts}'],
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/tests/setup.js'],
    alias: {
      '$lib': '/src/lib',
    },
    server: {
      deps: {
        inline: [/svelte/],
      },
    },
  },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 5173,
    strictPort: true,
    // Phase 0.1 live-test fix: WebView2 на Windows резолвит "localhost" в IPv6 (::1).
    // Vite default (host: false) слушает только на IPv4 127.0.0.1 → ERR_CONNECTION_TIMED_OUT.
    // Явный 127.0.0.1 синхронизирует резолв с tauri.conf.json devUrl.
    // Port 1420 на машине Антона зависал в SYN_RECEIVED (Hyper-V/HNS dynamic claim);
    // 5173 (Vite default) — clean.
    host: host || "127.0.0.1",
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
