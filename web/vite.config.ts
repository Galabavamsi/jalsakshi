/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// `vite --mode mock` (pnpm dev:mock) runs the console on seeded demo data with auth skipped.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: { target: 'es2020', sourcemap: true },
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
  },
});
