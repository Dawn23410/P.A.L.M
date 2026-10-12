/**
 * 模块清单（唯一需要改动的注册点）
 * =================================
 * 新增页面 = 加一行 registerPage + 在 pages/ 下放一个模块文件。
 * 侧边栏由这份清单自动生成，无需改 index.html。
 *
 * 页面在内核里登记为同名插件（page:<id>），真正的加载 / 卸载 /
 * 回滚交给底层框架 kernel（见 core/loader.js）。
 */
import { registerPage } from './loader.js';

registerPage('home', {
  title: '主页',
  src: '../pages/home.js',
});

registerPage('overview', {
  title: '概况',
  src: '../pages/overview.js',
});

registerPage('chat', {
  title: '聊天',
  src: '../pages/chat.js',
});

registerPage('settings', {
  title: '设置',
  src: '../pages/settings.js',
});
