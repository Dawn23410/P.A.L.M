import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  root: 'src',
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    chunkSizeWarningLimit: 2000,
  },
  server: {
    port: 43210,
    strictPort: false,
    host: true,
  },
});
