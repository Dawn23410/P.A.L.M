/**
 * P.A.L.M · Config Schemas
 * ─────────────────────────
 * 模块配置的"单点真相"：默认值 + 分组元数据
 * 每个模块的配置结构定义在此，store 层据此做默认值合并与类型推断。
 *
 * 数据流：configSchema.ts (默认值+分组元数据)
 *              ↓
 *       configStore.ts (zustand + 防抖持久化)
 *              ↓
 *       各模块页面 (useModuleConfig hook 消费)
 */

// ─── 模块 ID ────────────────────────────────────────────────────

export type ModuleId =
  | 'dashboard'
  | 'wallpaper'
  | 'dock'
  | 'agent'
  | 'asr'
  | 'tts';

export const ALL_MODULES: ModuleId[] = [
  'dashboard',
  'wallpaper',
  'dock',
  'agent',
  'asr',
  'tts',
];

export const MODULE_LABELS: Record<ModuleId, string> = {
  dashboard: '仪表盘',
  wallpaper: '壁纸引擎',
  dock: 'Dock 栏',
  agent: 'Agent',
  asr: '语音识别',
  tts: '语音播报',
};

// ─── 字段元数据类型 ─────────────────────────────────────────────

export type FieldType =
  | 'select'
  | 'slider'
  | 'switch'
  | 'color'
  | 'input'
  | 'password'
  | 'number'
  | 'textarea'
  | 'hotkey'
  | 'segmented';

export interface FieldMeta {
  key: string;
  label: string;
  type: FieldType;
  defaultValue: unknown;
  options?: { label: string; value: unknown }[];
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  description?: string;
  /** 当 value 等于此值时，依赖字段会显示 */
  showWhen?: { field: string; eq: unknown };
}

export interface ConfigGroup {
  title: string;
  fields: FieldMeta[];
}

export interface ModuleSchema {
  id: ModuleId;
  name: string;
  groups: ConfigGroup[];
}

// ─── 默认值（按模块） ───────────────────────────────────────────

export const DEFAULT_CONFIGS: Record<ModuleId, Record<string, unknown>> = {
  // ── 仪表盘 ───────────────────────────────────────────────
  dashboard: {
    refreshInterval: 1,
    visibleWidgets: ['system', 'network', 'storage', 'services'],
  },

  // ── 壁纸引擎 ──────────────────────────────────────────────
  wallpaper: {
    wallpaperPath: '',
    scaleMode: 'fill',
    accentColor: '#00e5ff',
    randomSwitch: false,
    switchInterval: 300,
    multiMonitor: 'extend',
    pauseOnBattery: false,
    allowVideo: true,
  },

  // ── Dock 栏 ──────────────────────────────────────────────
  dock: {
    position: 'bottom',
    iconSize: 48,
    magnification: true,
    magnificationScale: 1.2,
    opacity: 0.85,
    themeColor: '#00e5ff',
    autoHide: false,
    showDelay: 300,
    hideDelay: 500,
    hotkey: 'Alt+Space',
    showRunningIndicator: true,
    trashEnabled: true,
  },

  // ── Agent ────────────────────────────────────────────────
  agent: {
    provider: 'openai',
    apiKey: '',
    apiEndpoint: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    timeout: 30,
    integrations: {
      wechat: false,
      wecom: false,
      telegram: false,
      email: false,
      slack: false,
    },
    customModelPath: '',
    authToken: '',
    gatewayMode: 'direct',
    personality: 'assistant',
    memoryEnabled: true,
    memoryRetention: 7,
  },

  // ── 语音识别 ──────────────────────────────────────────────
  asr: {
    engine: 'local',
    apiKey: '',
    secretKey: '',
    sampleRate: 16000,
    language: 'zh-CN',
    autoPunctuation: true,
    hotwords: '',
    wakeWord: '',
    continuousMode: false,
    silenceTimeout: 3,
    noiseSuppression: true,
    vadLevel: 'medium',
  },

  // ── 语音播报 ──────────────────────────────────────────────
  tts: {
    engine: 'local',
    voice: 'zh-CN-XiaoxiaoNeural',
    speed: 1.0,
    pitch: 1.0,
    volume: 1.0,
    apiKey: '',
    cacheEnabled: true,
    cachePath: '',
    autoPlay: false,
    rateLimit: 50,

    // ── 主页面状态 ──
    selectedModel: 'gpt-sovits',
    selectedSection: 'voice',

    // ── GPT-SoVITS 配置 ──
    gsvDevice: 'cuda:0',
    gsvHalfPrecision: true,
    gsvStreaming: false,
    gsvDeterministic: false,
    gsvSynthLang: '中文',
    gsvCutMethod: '不切',
    gsvActivePkg: '',

    // ── 语音合成参数 ──
    customVoiceSpeaker: 'Vivian',
    customVoiceLanguage: 'auto',
    customVoiceInstruct: '',
    customVoiceTemperature: 1.0,
    customVoiceTopK: 50,
    customVoiceTopP: 0.9,
    customVoiceMaxNewTokens: 2048,

    // ── 音色设计参数 ──
    voiceDesignInstruct: '',
    voiceDesignLanguage: 'auto',

    // ── 语音克隆参数 ──
    voiceCloneLanguage: 'auto',
    voiceCloneMode: 'x-vector',

    // ── GSV 语音克隆参数 ──
    gsCloneSpeed: 1.0,
    gsClonePauseSec: 0.3,
    gsCloneTopK: 20,
    gsCloneTopP: 0.8,
    gsCloneTemperature: 0.8,

    // ── CosyVoice 自然语言控制参数 ──
    cosyDefaultSpeaker: '',
    cosySelectedSpeaker: '',
    cosySpeed: 1.0,
    cosySeed: 0,
    cosyStream: false,
    cosyText: '我是通义实验室语音团队全新推出的生成式语音大模型，提供舒适自然的语音合成能力。',
    cosyInstruct: '',
    cosyDevice: 'cuda:0',
    cosyHalfPrecision: false,
  },
};


// ─── 分组元数据（用于自动生成表单） ────────────────────────────

const GROUPS: Record<ModuleId, ConfigGroup[]> = {
  dashboard: [
    {
      title: '刷新型为',
      fields: [
        { key: 'refreshInterval', label: '刷新间隔', type: 'number', defaultValue: 1, min: 1, max: 300, step: 1, description: '秒' },
      ],
    },
    {
      title: '可见组件',
      fields: [
        { key: 'visibleWidgets', label: '系统组件', type: 'select', defaultValue: ['system', 'network', 'storage', 'services'], options: [
          { label: '系统信息', value: 'system' },
          { label: '网络状态', value: 'network' },
          { label: '存储空间', value: 'storage' },
          { label: '服务状态', value: 'services' },
        ] },
      ],
    },
  ],

  wallpaper: [
    {
      title: '壁纸设置',
      fields: [
        { key: 'wallpaperPath', label: '壁纸路径', type: 'input', defaultValue: '', placeholder: '选择壁纸文件或目录…' },
        { key: 'scaleMode', label: '缩放模式', type: 'select', defaultValue: 'fill', options: [
          { label: '填充', value: 'fill' },
          { label: '适应', value: 'fit' },
          { label: '拉伸', value: 'stretch' },
          { label: '居中', value: 'center' },
          { label: '跨屏', value: 'span' },
        ] },
        { key: 'accentColor', label: '强调色', type: 'color', defaultValue: '#00e5ff' },
        { key: 'allowVideo', label: '允许视频壁纸', type: 'switch', defaultValue: true },
      ],
    },
    {
      title: '自动切换',
      fields: [
        { key: 'randomSwitch', label: '随机切换', type: 'switch', defaultValue: false },
        { key: 'switchInterval', label: '切换间隔', type: 'number', defaultValue: 300, min: 10, max: 86400, step: 10, description: '秒', showWhen: { field: 'randomSwitch', eq: true } },
        { key: 'multiMonitor', label: '多显示器', type: 'select', defaultValue: 'extend', options: [
          { label: '复制', value: 'duplicate' },
          { label: '扩展', value: 'extend' },
          { label: '单屏', value: 'single' },
        ] },
        { key: 'pauseOnBattery', label: '电池时暂停', type: 'switch', defaultValue: false },
      ],
    },
  ],

  dock: [
    {
      title: '外观',
      fields: [
        { key: 'position', label: '位置', type: 'select', defaultValue: 'bottom', options: [
          { label: '底部', value: 'bottom' },
          { label: '左侧', value: 'left' },
          { label: '右侧', value: 'right' },
        ] },
        { key: 'iconSize', label: '图标大小', type: 'slider', defaultValue: 48, min: 24, max: 96, step: 4 },
        { key: 'themeColor', label: '主题色', type: 'color', defaultValue: '#00e5ff' },
        { key: 'opacity', label: '不透明度', type: 'slider', defaultValue: 0.85, min: 0.1, max: 1, step: 0.05 },
        { key: 'showRunningIndicator', label: '运行指示器', type: 'switch', defaultValue: true },
      ],
    },
    {
      title: '交互',
      fields: [
        { key: 'magnification', label: '放大效果', type: 'switch', defaultValue: true },
        { key: 'magnificationScale', label: '放大倍率', type: 'slider', defaultValue: 1.2, min: 1.0, max: 2.0, step: 0.1, showWhen: { field: 'magnification', eq: true } },
        { key: 'autoHide', label: '自动隐藏', type: 'switch', defaultValue: false },
        { key: 'showDelay', label: '显示延迟', type: 'number', defaultValue: 300, min: 50, max: 3000, step: 50, description: 'ms' },
        { key: 'hideDelay', label: '隐藏延迟', type: 'number', defaultValue: 500, min: 50, max: 3000, step: 50, description: 'ms' },
        { key: 'hotkey', label: '全局快捷键', type: 'hotkey', defaultValue: 'Alt+Space' },
        { key: 'trashEnabled', label: '显示垃圾桶', type: 'switch', defaultValue: true },
      ],
    },
  ],

  agent: [
    {
      title: 'API 连接',
      fields: [
        { key: 'provider', label: 'API 供应商', type: 'select', defaultValue: 'openai', options: [
          { label: 'OpenAI', value: 'openai' },
          { label: 'Azure', value: 'azure' },
          { label: 'Anthropic', value: 'anthropic' },
          { label: '本地', value: 'local' },
          { label: '自定义', value: 'custom' },
        ] },
        { key: 'apiKey', label: 'API Key', type: 'password', defaultValue: '', placeholder: 'sk-...' },
        { key: 'apiEndpoint', label: 'API 端点', type: 'input', defaultValue: 'https://api.openai.com/v1', placeholder: 'https://…' },
        { key: 'gatewayMode', label: '网关模式', type: 'select', defaultValue: 'direct', options: [
          { label: '直连', value: 'direct' },
          { label: '反向代理', value: 'reverse' },
          { label: '本地网关', value: 'local' },
        ] },
        { key: 'authToken', label: '认证令牌', type: 'password', defaultValue: '', placeholder: '可选' },
      ],
    },
    {
      title: '模型',
      fields: [
        { key: 'model', label: 'AI 模型', type: 'select', defaultValue: 'gpt-4o', options: [
          { label: 'GPT-4o', value: 'gpt-4o' },
          { label: 'GPT-4o-mini', value: 'gpt-4o-mini' },
          { label: 'Claude 3.5 Sonnet', value: 'claude-3.5-sonnet' },
          { label: '本地模型', value: 'local' },
        ] },
        { key: 'customModelPath', label: '自定义模型路径', type: 'input', defaultValue: '', placeholder: '/path/to/model', showWhen: { field: 'model', eq: 'local' } },
        { key: 'timeout', label: '请求超时', type: 'number', defaultValue: 30, min: 5, max: 300, step: 5, description: '秒' },
        { key: 'personality', label: '人格设定', type: 'select', defaultValue: 'assistant', options: [
          { label: '助手', value: 'assistant' },
          { label: '创意', value: 'creative' },
          { label: '专业', value: 'professional' },
        ] },
      ],
    },
    {
      title: '记忆与集成',
      fields: [
        { key: 'memoryEnabled', label: '启用记忆', type: 'switch', defaultValue: true },
        { key: 'memoryRetention', label: '记忆保留', type: 'number', defaultValue: 7, min: 1, max: 90, step: 1, description: '天', showWhen: { field: 'memoryEnabled', eq: true } },
        { key: 'integrations', label: '通讯集成', type: 'switch', defaultValue: false, description: '各平台开关（在表单页面展示为独立 Switch）' },
      ],
    },
  ],

  asr: [
    {
      title: '引擎',
      fields: [
        { key: 'engine', label: '识别引擎', type: 'select', defaultValue: 'local', options: [
          { label: '本地', value: 'local' },
          { label: '百度', value: 'baidu' },
          { label: '阿里', value: 'aliyun' },
          { label: '腾讯', value: 'tencent' },
          { label: '讯飞', value: 'iflytek' },
        ] },
        { key: 'apiKey', label: 'API Key', type: 'password', defaultValue: '' },
        { key: 'secretKey', label: 'Secret Key', type: 'password', defaultValue: '' },
        { key: 'sampleRate', label: '采样率', type: 'select', defaultValue: 16000, options: [
          { label: '16kHz', value: 16000 },
          { label: '8kHz', value: 8000 },
        ] },
        { key: 'language', label: '识别语言', type: 'select', defaultValue: 'zh-CN', options: [
          { label: '中文', value: 'zh-CN' },
          { label: '英文', value: 'en-US' },
          { label: '粤语', value: 'yue-CN' },
          { label: '中英混', value: 'mixed' },
        ] },
      ],
    },
    {
      title: '高级',
      fields: [
        { key: 'autoPunctuation', label: '自动标点', type: 'switch', defaultValue: true },
        { key: 'continuousMode', label: '连续识别', type: 'switch', defaultValue: false },
        { key: 'silenceTimeout', label: '静默超时', type: 'number', defaultValue: 3, min: 1, max: 30, step: 1, description: '秒' },
        { key: 'noiseSuppression', label: '降噪', type: 'switch', defaultValue: true },
        { key: 'vadLevel', label: '语音活动检测', type: 'select', defaultValue: 'medium', options: [
          { label: '低', value: 'low' },
          { label: '中', value: 'medium' },
          { label: '高', value: 'high' },
        ] },
        { key: 'hotwords', label: '热词列表', type: 'textarea', defaultValue: '', placeholder: '每行一个热词' },
        { key: 'wakeWord', label: '唤醒词', type: 'input', defaultValue: '', placeholder: '如：嘿 PALM' },
      ],
    },
  ],

  tts: [
    {
      title: '引擎',
      fields: [
        { key: 'engine', label: '播报引擎', type: 'select', defaultValue: 'local', options: [
          { label: '本地', value: 'local' },
          { label: '百度', value: 'baidu' },
          { label: '阿里', value: 'aliyun' },
          { label: '腾讯', value: 'tencent' },
          { label: '讯飞', value: 'iflytek' },
        ] },
        { key: 'voice', label: '语音', type: 'select', defaultValue: 'zh-CN-XiaoxiaoNeural', options: [
          { label: '晓晓（女）', value: 'zh-CN-XiaoxiaoNeural' },
          { label: '云希（男）', value: 'zh-CN-YunxiNeural' },
          { label: '晓伊（女）', value: 'zh-CN-XiaoyiNeural' },
          { label: '云扬（男）', value: 'zh-CN-YunyangNeural' },
        ] },
        { key: 'apiKey', label: 'API Key', type: 'password', defaultValue: '' },
        { key: 'autoPlay', label: '开机自动播报', type: 'switch', defaultValue: false },
      ],
    },
    {
      title: '音质',
      fields: [
        { key: 'speed', label: '语速', type: 'slider', defaultValue: 1.0, min: 0.5, max: 2.0, step: 0.1 },
        { key: 'pitch', label: '音调', type: 'slider', defaultValue: 1.0, min: 0.5, max: 2.0, step: 0.1 },
        { key: 'volume', label: '音量', type: 'slider', defaultValue: 1.0, min: 0, max: 1.0, step: 0.05 },
      ],
    },
    {
      title: '缓存',
      fields: [
        { key: 'cacheEnabled', label: '启用缓存', type: 'switch', defaultValue: true },
        { key: 'cachePath', label: '缓存路径', type: 'input', defaultValue: '', placeholder: '默认缓存位置', showWhen: { field: 'cacheEnabled', eq: true } },
        { key: 'rateLimit', label: '每分钟限制', type: 'number', defaultValue: 50, min: 10, max: 500, step: 10, description: '次/分钟' },
      ],
    },
    {
      title: '会话状态（自动保存）',
      fields: [
        { key: 'selectedModel', label: '当前模型', type: 'select', defaultValue: 'gpt-sovits', options: [
          { label: 'GPT-SoVITS', value: 'gpt-sovits' },
        ] },
        { key: 'selectedSection', label: '当前功能', type: 'select', defaultValue: 'voice', options: [
          { label: '语音合成', value: 'voice' },
          { label: '音色设计', value: 'design' },
          { label: '语音克隆', value: 'clone' },
        ] },
      ],
    },
  ],
};

/** 获取模块的完整 Schema（含分组和字段元数据） */
export function getModuleSchema(moduleId: ModuleId): ModuleSchema {
  return {
    id: moduleId,
    name: MODULE_LABELS[moduleId],
    groups: GROUPS[moduleId],
  };
}

/** 获取所有模块的 Schema 数组 */
export function getAllSchemas(): ModuleSchema[] {
  return ALL_MODULES.map(getModuleSchema);
}

// ─── TTS 模块配置类型（供组件使用） ─────────────────────────────

export interface TtsConfig {
  engine: string;
  voice: string;
  speed: number;
  pitch: number;
  volume: number;
  apiKey: string;
  cacheEnabled: boolean;
  cachePath: string;
  autoPlay: boolean;
  rateLimit: number;
  selectedModel: string;
  selectedSection: string;
  gsvDevice: string;
  gsvHalfPrecision: boolean;
  gsvStreaming: boolean;
  gsvDeterministic: boolean;
  gsvSynthLang: string;
  gsvCutMethod: string;
  gsvActivePkg: string;
  customVoiceSpeaker: string;
  customVoiceLanguage: string;
  customVoiceInstruct: string;
  customVoiceTemperature: number;
  customVoiceTopK: number;
  customVoiceTopP: number;
  customVoiceMaxNewTokens: number;
  voiceDesignInstruct: string;
  voiceDesignLanguage: string;
  voiceCloneLanguage: string;
  voiceCloneMode: string;
  gsCloneSpeed: number;
  gsClonePauseSec: number;
  gsCloneTopK: number;
  gsCloneTopP: number;
  gsCloneTemperature: number;

  // ── CosyVoice 自然语言控制 ──
  cosyDefaultSpeaker: string;
  cosySelectedSpeaker: string;
  cosySpeed: number;
  cosySeed: number;
  cosyStream: boolean;
  cosyText: string;
  cosyInstruct: string;
  cosyDevice: string;
  cosyHalfPrecision: boolean;
}
