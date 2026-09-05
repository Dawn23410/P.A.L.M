import { useEffect, useMemo, useState } from 'react';
import { Card, Tag, Input, Button, Progress, Empty, Spin, message } from 'antd';
import { ApiOutlined, SafetyCertificateOutlined, BranchesOutlined } from '@ant-design/icons';
import {
  getFaces,
  getGuardrail,
  routeIntent,
  INTENT_LABELS,
  type FaceInfo,
  type GuardrailInfo,
  type RouteResult,
} from '../api/mentalcore';
import { pingMentalCore } from '../api/chat';

/** 好感度数值映射到 0~100 进度（base -50~100 / dynamics -50~50） */
function toPct(v: number, lo: number, hi: number) {
  const pct = ((v - lo) / (hi - lo)) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

function FaceStateRow({ k, v }: { k: string; v: unknown }) {
  if (Array.isArray(v)) {
    return (
      <div className="mc-kv">
        <span className="mc-kv__k">{k}</span>
        <span className="mc-kv__v">{v.length ? v.join('、') : '—'}</span>
      </div>
    );
  }
  if (typeof v === 'boolean') {
    return (
      <div className="mc-kv">
        <span className="mc-kv__k">{k}</span>
        <span className="mc-kv__v">{v ? '开' : '关'}</span>
      </div>
    );
  }
  return (
    <div className="mc-kv">
      <span className="mc-kv__k">{k}</span>
      <span className="mc-kv__v">{v === '' || v === null || v === undefined ? '—' : String(v)}</span>
    </div>
  );
}

export default function MentalCore() {
  const [online, setOnline] = useState(false);
  const [faces, setFaces] = useState<FaceInfo[]>([]);
  const [guardrail, setGuardrail] = useState<GuardrailInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const [routeText, setRouteText] = useState('');
  const [routeResult, setRouteResult] = useState<RouteResult | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);

  const emotionFace = useMemo(
    () => faces.find((f) => f.name === 'emotion'),
    [faces],
  );
  const personaFace = useMemo(
    () => faces.find((f) => f.name === 'persona'),
    [faces],
  );

  const load = async () => {
    setLoading(true);
    const mc = await pingMentalCore().catch(() => ({ online: false }));
    setOnline(mc.online);
    if (!mc.online) {
      setLoading(false);
      return;
    }
    try {
      const [f, g] = await Promise.all([getFaces(), getGuardrail()]);
      setFaces(f);
      setGuardrail(g);
    } catch (e) {
      message.error(`加载心智魔方状态失败：${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onRoute = async () => {
    const text = routeText.trim();
    if (!text) return;
    setRouteLoading(true);
    try {
      const r = await routeIntent(text);
      setRouteResult(r);
    } catch (e) {
      message.error(`路由判定失败：${(e as Error).message}`);
    } finally {
      setRouteLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="mc-loading">
        <Spin tip="加载心智魔方…" />
      </div>
    );
  }

  if (!online) {
    return (
      <div className="mc-page">
        <div className="mc-header">
          <h2 className="mc-title">
            <ApiOutlined /> 心智魔方 · 大脑可视化
          </h2>
        </div>
        <Empty
          description={
            <span>
              织语层桥接未连接（默认 <code>127.0.0.1:7788</code>）。
              <br />
              请确认一键启动脚本已拉起 MENTALCORE 服务，或运行 <code>mentalcore/run_bridge.bat</code>。
            </span>
          }
        />
      </div>
    );
  }

  return (
    <div className="mc-page">
      <div className="mc-header">
        <h2 className="mc-title">
          <ApiOutlined /> 心智魔方 · 大脑可视化
        </h2>
        <Tag color="green" className="mc-online">
          在线 · {guardrail?.mode ?? 'mock'}
        </Tag>
      </div>

      {/* 人格卡 */}
      {personaFace && (
        <Card size="small" className="mc-card" title="人格卡 (Persona)">
          <div className="mc-persona">
            <div className="mc-persona__name">{String(personaFace.state.name)}</div>
            <div className="mc-persona__tag">{String(personaFace.state.tagline)}</div>
            <div className="mc-pillars">
              {(personaFace.state.pillars as string[])?.map((p) => (
                <Tag key={p} color="blue">
                  {p}
                </Tag>
              ))}
              {(personaFace.state.flaws as string[])?.map((p) => (
                <Tag key={p} color="volcano">
                  {p}
                </Tag>
              ))}
            </div>
            <FaceStateRow k="语气" v={personaFace.state.tone} />
            <FaceStateRow k="话痨程度" v={personaFace.state.talkativeness} />
            <FaceStateRow k="年龄" v={personaFace.state.age} />
            <FaceStateRow k="背景" v={personaFace.state.background} />
            <FaceStateRow k="示例对话" v={personaFace.state.example} />
          </div>
        </Card>
      )}

      {/* 六面网格 */}
      <div className="mc-faces">
        {faces.map((f) => (
          <Card
            key={f.name}
            size="small"
            className="mc-card mc-face"
            title={
              <span>
                <BranchesOutlined /> {f.label}
              </span>
            }
          >
            <div className="mc-face__desc">{f.description}</div>
            {f.name === 'emotion' && emotionFace ? (
              <div className="mc-affinity">
                <div className="mc-affinity__stage">
                  关系等级：<strong>{String(emotionFace.state.stage_name)}</strong>
                  {emotionFace.state.affinity_enabled === false && (
                    <Tag color="default" style={{ marginLeft: 6 }}>
                      情感面已关闭
                    </Tag>
                  )}
                </div>
                <div className="mc-affinity__row">
                  <span>信任地基 base</span>
                  <Progress
                    percent={toPct(Number(emotionFace.state.base), -50, 100)}
                    showInfo
                    size="small"
                    strokeColor="#2dd4bf"
                  />
                  <span className="mc-affinity__num">
                    {Number(emotionFace.state.base).toFixed(1)}
                  </span>
                </div>
                <div className="mc-affinity__row">
                  <span>当下心情 dynamics</span>
                  <Progress
                    percent={toPct(Number(emotionFace.state.dynamics), -50, 50)}
                    showInfo
                    size="small"
                    strokeColor="#f59e0b"
                  />
                  <span className="mc-affinity__num">
                    {Number(emotionFace.state.dynamics).toFixed(1)}
                  </span>
                </div>
                <div className="mc-affinity__row">
                  <span>羁绊 bond</span>
                  <span className="mc-affinity__num">
                    {Number(emotionFace.state.bond).toFixed(2)}
                  </span>
                </div>
              </div>
            ) : (
              <div className="mc-state">
                {Object.entries(f.state).map(([k, v]) => (
                  <FaceStateRow key={k} k={k} v={v} />
                ))}
              </div>
            )}
          </Card>
        ))}
      </div>

      {/* 护栏配置 */}
      {guardrail && (
        <Card
          size="small"
          className="mc-card"
          title={
            <span>
              <SafetyCertificateOutlined /> 护栏 (Guardrail) 配置
            </span>
          }
        >
          <div className="mc-state">
            <FaceStateRow k="当前档位 profile" v={guardrail.profile} />
            <FaceStateRow k="运行模式 mode" v={guardrail.mode} />
            <FaceStateRow k="情绪识别 emotion_via_llm" v={guardrail.emotion_via_llm} />
            <FaceStateRow k="国密加密 crypto_enabled" v={guardrail.crypto_enabled} />
            <FaceStateRow k="规则文件 rules_yaml" v={guardrail.rules_yaml || '（内置默认）'} />
          </div>
          <div className="mc-tiers">
            <span className="mc-kv__k">可选档位：</span>
            {guardrail.tiers.map((t) => (
              <Tag key={t} color={t === guardrail.profile ? 'green' : 'default'}>
                {t}
              </Tag>
            ))}
          </div>
          <div className="mc-note">{guardrail.note}</div>
        </Card>
      )}

      {/* 意图路由测试器 */}
      <Card size="small" className="mc-card" title="意图路由 (IntentRouter) 测试">
        <div className="mc-route">
          <Input.TextArea
            value={routeText}
            onChange={(e) => setRouteText(e.target.value)}
            placeholder="输入一句话，查看 Boss/Worker 双链会如何路由（闲聊 / 任务 / 干预 / 查询）"
            autoSize={{ minRows: 2, maxRows: 4 }}
          />
          <Button
            type="primary"
            loading={routeLoading}
            onClick={onRoute}
            disabled={!routeText.trim()}
            style={{ marginTop: 8 }}
          >
            判定意图
          </Button>
        </div>
        {routeResult && (
          <div className="mc-route__result">
            <Tag color="geekblue">{INTENT_LABELS[routeResult.intent] ?? routeResult.intent}</Tag>
            {routeResult.task_goal && (
              <span className="mc-route__goal">目标：{routeResult.task_goal}</span>
            )}
            {routeResult.intervention_action && (
              <span className="mc-route__goal">动作：{routeResult.intervention_action}</span>
            )}
            <div className="mc-note">{routeResult.note}</div>
          </div>
        )}
      </Card>
    </div>
  );
}
