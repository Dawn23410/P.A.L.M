/**
 * 极简 hash 路由（框架无关）
 * - 不持有任何页面实现，只负责「当前应该显示哪个页面 id」
 * - 通过事件通知外部，避免与渲染逻辑耦合
 */
export class Router {
  constructor(defaultPage = 'home') {
    this.defaultPage = defaultPage;
    this.listeners = new Set();
    this._onHashChange = () => this._emit(this.current);
    window.addEventListener('hashchange', this._onHashChange);
  }

  get current() {
    const id = location.hash.replace(/^#/, '');
    return id || this.defaultPage;
  }

  /**
   * 主动跳转。
   * ⚠️ 只通知一次：hash 变化交给 hashchange 统一通知；
   *    hash 没变（比如点的是当前页）才由这里兜底同步通知。
   *    若两者都做，一次跳转会 _emit 两次 → 订阅方收到两条重复事件。
   */
  go(id) {
    const target = id || this.defaultPage;
    if (location.hash !== '#' + target) {
      location.hash = target;          // 由 hashchange 触发唯一一次通知
    } else {
      this._emit(target);              // hash 未变，兜底同步通知
    }
  }

  /** 订阅路由变化，返回取消订阅函数 */
  onChange(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  _emit(id) {
    this.listeners.forEach((fn) => {
      try {
        fn(id);
      } catch (err) {
        // 单个订阅者出错不影响其他订阅者
        console.error('[Router] listener error:', err);
      }
    });
  }

  destroy() {
    window.removeEventListener('hashchange', this._onHashChange);
    this.listeners.clear();
  }
}
