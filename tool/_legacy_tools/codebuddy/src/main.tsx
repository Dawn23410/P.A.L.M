import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ConfigProvider, theme as antdTheme, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useThemeStore } from './store/themeStore';
import { Layout } from './components/Layout';
import Dashboard from './pages/Dashboard';
import ModuleManagement from './pages/ModuleManagement';
import TtsMainPage from './pages/TtsMainPage';
import GsAdvancedConfig from './pages/GsAdvancedConfig';
import './styles/styles.css';
import './styles/qwen-tts.css';

function Placeholder() {
  const location = useLocation();
  const titles: Record<string, { en: string; cn: string }> = {
    '/dashboard': { en: 'System Dashboard', cn: '仪表盘' },
    '/wallpaper': { en: 'Wallpaper Engine', cn: '壁纸引擎' },
    '/dock': { en: 'Dock Panel', cn: 'Dock 栏' },
    '/agent': { en: 'Agent', cn: 'Agent' },
    '/asr': { en: 'Speech Recognition', cn: '语音识别' },
    '/tts': { en: 'Qwen3-TTS', cn: '语音播报' },
  };
  const meta = titles[location.pathname] ?? { en: '', cn: '未知模块' };

  return (
    <>
      <div className="palm-page__title-row palm-page__title-row--compact">
        <div>
          <div className="palm-page__subtitle">{meta.en}</div>
          <h2 className="palm-page__title">{meta.cn}</h2>
        </div>
      </div>

      <div className="palm-card-placeholder">
        正在开发中.....
      </div>
    </>
  );
}

function Shell() {
  const resolved = useThemeStore((s) => s.resolved);

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: resolved === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: '#00e5ff',
          borderRadius: 4,
          fontSize: 13,
        },
      }}
    >
      <AntdApp>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/wallpaper" element={<Placeholder />} />
              <Route path="/dock" element={<Placeholder />} />
              <Route path="/agent" element={<Placeholder />} />
              <Route path="/asr" element={<Placeholder />} />
              <Route path="/tts" element={<TtsMainPage />} />
              <Route path="/tts/gs-advanced" element={<GsAdvancedConfig />} />
              <Route path="/modules" element={<ModuleManagement />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}

const container = document.getElementById('root');
if (container) {
  createRoot(container).render(<Shell />);
}
