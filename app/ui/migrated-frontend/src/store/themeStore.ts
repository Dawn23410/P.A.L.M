import { create } from 'zustand';

export type ThemeMode = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'palm.theme.v1';

function readStored(): ThemeMode {
  const v = localStorage.getItem(STORAGE_KEY);
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
}

export interface ThemeStore {
  mode: ThemeMode;
  resolved: 'light' | 'dark';
  setMode: (m: ThemeMode) => void;
}

function resolveSystem(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export const useThemeStore = create<ThemeStore>((set) => ({
  mode: readStored(),
  resolved: readStored() === 'system' ? resolveSystem() : (readStored() as 'light' | 'dark'),
  setMode: (m) => {
    localStorage.setItem(STORAGE_KEY, m);
    const resolved = m === 'system' ? resolveSystem() : m;
    set({ mode: m, resolved });
  },
}));

// 监听系统主题变化
if (typeof window !== 'undefined') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    const s = useThemeStore.getState();
    if (s.mode === 'system') {
      useThemeStore.setState({ resolved: e.matches ? 'dark' : 'light' });
    }
  });
}
