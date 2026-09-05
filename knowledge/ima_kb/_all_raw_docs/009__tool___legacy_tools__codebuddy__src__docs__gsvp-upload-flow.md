# GSVP 整合包上传流程

## 触发方式

### 方式一：点击「添加整合包」按钮
1. 用户点击主界面「添加整合包」按钮
2. 弹出系统文件选择器，过滤 `.gsvp` 文件
3. 用户选择文件后触发 `handlePkgChange`

### 方式二：拖拽文件到整合包列表区域
1. 用户将 `.gsvp` 文件拖入指定区域
2. 拖入时区域高亮（蓝色边框 + 蓝色背景）
3. 释放文件后触发 `handleDrop`

## 流程

```
用户选择/拖入 .gsvp 文件
  ↓
前端 FormData 封装文件
  ↓
POST /packages/upload → 后端保存到 packages/ 目录
  ↓
提取文件名（去掉 .gsvp 后缀）
  ↓
直接添加到前端包列表 state
  ↓
卡片显示：
  📂 包名    参考语种: -   模型版本: -   参考音频: 0 个    [使用该模型]  [删除]
```

## 后端接口

### `POST /packages/upload`

- Content-Type: `multipart/form-data`
- Body: `{ file: <binary> }`
- 后端将文件保存到 `BASE_DIR`（默认 `runtime/packages/`）
- 返回: `{ success: true, path: "..." , name: "..." }`

### `GET /packages/search`

- 扫描 `BASE_DIR` 下所有子目录中的 `config.json`
- 返回已解压/提取的整合包列表
- 当前未实现 7z 解压，所以上传的 `.gsvp` 仅作为文件保存

## 前端关键代码

```typescript
// handlePkgChange / handleDrop - 上传流程
const formData = new FormData();
formData.append('file', file);
const uploadResp = await fetch('http://127.0.0.1:5000/packages/upload', {
  method: 'POST',
  body: formData,
});
const result = await uploadResp.json();
const name = file.name.replace(/\.gsvp$/i, '');
setPackages((prev) => [...prev, {
  name, refLang: '-', cutMethod: '-', modelVersion: '-', audioCount: 0,
}]);
```

## 文件位置

- 后端保存目录: `D:\Desktop\Codebuddy\runtime\packages\`
- 前端源文件: `src/pages/TtsMainPage.tsx` (handlePkgChange / handleDrop)
- 后端源文件: `runtime/server.py` (/packages/upload)
