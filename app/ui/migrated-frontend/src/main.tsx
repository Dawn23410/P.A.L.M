import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, theme as antdTheme, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useThemeStore } from './store/themeStore';
import { Layout } from './components/Layout';
import Console from './pages/Console';
import TtsMainPage from './pages/TtsMainPage';
import TtsWelcome from './pages/TtsWelcome';
import CosyControl from './pages/CosyControl';
import GsAdvancedConfig from './pages/GsAdvancedConfig';
import Chat from './pages/Chat';
import MentalCore from './pages/MentalCore';
import './styles/styles.css';
import './styles/gsv.css';

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
          ...(resolved === 'dark'
            ? {
                colorBgContainer: '#161b22',
                colorBgElevated: '#1c2128',
                colorBgLayout: '#0d1117',
                colorBgSpotlight: '#1c2128',
                colorBorder: 'rgba(255,255,255,0.12)',
                colorBorderSecondary: 'rgba(255,255,255,0.08)',
                colorSplit: 'rgba(255,255,255,0.08)',
                colorText: '#e6edf3',
                colorTextSecondary: '#c9d1d9',
                colorTextTertiary: '#8b949e',
              }
            : {}),
        },
      }}
    >
      <AntdApp>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/console" replace />} />
            <Route path="/console" element={<Console />} />
            <Route path="/tts" element={<TtsWelcome />} />
            <Route path="/tts/gpt-sovits" element={<TtsMainPage />} />
            <Route path="/tts/cosyvoice" element={<CosyControl />} />
            <Route path="/tts/gs-advanced" element={<GsAdvancedConfig />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/mentalcore" element={<MentalCore />} />
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
