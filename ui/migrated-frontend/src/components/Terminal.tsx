import { useEffect, useRef } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useConsole, LEVEL_COLORS } from '../hooks/useConsole';

/**
 * P.A.L.M · 控制台终端
 * 纯终端外观：无标题栏 / 作用域标签 / 清屏按钮；输入行内联于输出流末行（无独立输入框）。
 * 仅执行内置命令（help / clear / ver / status / modules），不执行 Python / Bash 等代码。
 */
export default function Terminal() {
  const { lines, input, setInput, submitCommand, executing } = useConsole();
  const bodyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, executing]);

  const focusInput = () => inputRef.current?.focus();

  const onKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !executing) {
      submitCommand(input);
      setInput('');
    }
  };

  return (
    <div className="palm-terminal">
      <div className="palm-terminal__body" ref={bodyRef} onClick={focusInput}>
        {lines.map((line) => (
          <div
            key={line.id}
            className="palm-terminal__line"
            style={{ color: LEVEL_COLORS[line.level] }}
          >
            {line.text || ' '}
          </div>
        ))}
        {executing && (
          <div className="palm-terminal__line palm-terminal__executing">执行中…</div>
        )}
        <div className="palm-terminal__inputline">
          <span className="palm-terminal__prompt">P.A.L.M ❯</span>
          <input
            ref={inputRef}
            className="palm-terminal__field"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={executing ? '执行中…' : '输入命令，回车执行（help 查看帮助）'}
            disabled={executing}
            autoFocus
            spellCheck={false}
          />
        </div>
      </div>
    </div>
  );
}
