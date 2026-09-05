import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  root: 'src',
  // Pre-bundle heavy deps up front so the first dev cold-start is much faster
  // (avoids Vite auto-scanning 3500+ modules on every fresh start).
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'zustand',
      'axios',
      'antd',
      '@ant-design/icons',
    ],
  },
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    chunkSizeWarningLimit: 2000,
  },
  server: {
    port: 43210,
    strictPort: false,
    host: true,
  },
  preview: {
    port: 43210,
    strictPort: true,
    host: true,
  },
});
