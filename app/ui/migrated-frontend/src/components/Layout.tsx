import { useEffect, useState } from 'react';
import { Layout as AntLayout, Menu } from 'antd';
import type { MenuProps } from 'antd';
import { SoundOutlined, MessageOutlined, ControlOutlined, MenuUnfoldOutlined, MenuFoldOutlined, ApiOutlined } from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useThemeStore } from '../store/themeStore';

const { Sider } = AntLayout;

const menuItems: MenuProps['items'] = [
  { key: '/console', icon: <ControlOutlined />, label: '控制台' },
  {
    key: '/tts',
    icon: <SoundOutlined />,
    label: '语音播报',
    children: [
      { key: '/tts/gpt-sovits', label: 'GPT-SoVITS' },
      { key: '/tts/cosyvoice', label: 'CosyVoice' },
    ],
  },
  { key: '/chat', icon: <MessageOutlined />, label: '聊天' },
  { key: '/mentalcore', icon: <ApiOutlined />, label: '心智魔方' },
];

// Brand mark (3x3 grid logo)
function BrandMark() {
  return (
    <div className="palm-brand__mark" aria-hidden>
      <span /><span /><span /><span /><span /><span /><span /><span /><span />
    </div>
  );
}

// Top bar of the layout (content header row)
function TopBar() {
  const { mode, resolved, setMode } = useThemeStore();
  const [time, setTime] = useState('');

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const pad = (n: number) => n.toString().padStart(2, '0');
      setTime(`${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const themeLabel =
    mode === 'system' ? '跟随系统' : resolved === 'dark' ? '暗色' : '亮色';

  return (
    <header className="palm-topbar">
      <div className="palm-topbar__label">
        <span>P.A.L.M · 参数配置中心</span>
      </div>

      <div className="palm-topbar__label">
        <span>主题 · <strong style={{ color: 'var(--palm-text-high, #0b0f19)' }}>{themeLabel}</strong></span>
        <span>│</span>
        <div className="palm-segmented" role="tablist">
          <button
            className={mode === 'system' ? 'active' : ''}
            onClick={() => setMode('system')}
            type="button"
          >
            自动
          </button>
          <button
            className={mode === 'light' ? 'active' : ''}
            onClick={() => setMode('light')}
            type="button"
          >
            亮色
          </button>
          <button
            className={mode === 'dark' ? 'active' : ''}
            onClick={() => setMode('dark')}
            type="button"
          >
            暗色
          </button>
        </div>
        <span>│</span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{time}</span>
      </div>
    </header>
  );
}

export function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { resolved } = useThemeStore();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', resolved);
  }, [resolved]);

  return (
    <AntLayout className="palm-page-bg" style={{ height: '100vh', overflow: 'hidden' }}>
      <Sider
        collapsed={collapsed}
        width={232}
        theme={resolved}
        trigger={null}
      >
        <div className="palm-brand">
          <BrandMark />
          {!collapsed && (
            <div className="palm-brand__text">
              <div className="palm-brand__title">P.A.L.M</div>
              <div className="palm-brand__tag">Control · v1.0</div>
            </div>
          )}
          <button
            className="palm-brand__toggle"
            onClick={() => setCollapsed((c) => !c)}
            type="button"
            aria-label={collapsed ? '展开' : '收起'}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
        </div>

        <Menu
          theme={resolved}
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          onOpenChange={(keys) => {
            // 单击「语音播报」展开子菜单时，跳转到 TTS 欢迎页；
            // 若当前已在某子页面（/tts/...），则不劫持，仅作展开/收起
            if (keys.includes('/tts') && !location.pathname.startsWith('/tts/')) {
              navigate('/tts');
            }
          }}
          style={{ borderRight: 'none', padding: '10px 0' }}
        />
      </Sider>

      <AntLayout style={{ background: 'transparent', overflow: 'hidden' }}>
        <TopBar />

        <div className="palm-page">
          <Outlet />
        </div>
      </AntLayout>
    </AntLayout>
  );
}
