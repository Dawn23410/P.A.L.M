import Terminal from '../components/Terminal';

/**
 * 控制台页面（/console）
 * 仅保留可交互终端：移除全部仪表盘/概览/服务状态/原始数据区块。
 */
export default function Console() {
  return (
    <div className="palm-console palm-console--terminal">
      <Terminal />
    </div>
  );
}
