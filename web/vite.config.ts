/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';

export default defineConfig({
  plugins: [svelte(), svelteTesting()],
  // MapLibre is one lazy chunk (loaded when a run's map is shown), about 1.1 MB: expected.
  build: { chunkSizeWarningLimit: 1200 },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
});
