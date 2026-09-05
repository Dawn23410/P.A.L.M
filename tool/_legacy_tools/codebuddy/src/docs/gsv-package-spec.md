# GPT-SoVITS 整合包规范 v1.0

## 1. 概述

GPT-SoVITS 整合包（Package）是将 GPT 模型、SoVITS 模型、参考音频及相关元数据统一打包的标准格式，便于分发、加载与校验。

---

## 2. 文件扩展名

| 文件类型     | 扩展名 |
| ------------ | ------ |
| GPT 模型     | `.ckpt` |
| SoVITS 模型  | `.pth`  |
| 参考音频     | `.wav`  |
| 配置文件     | `.json` |
| 打包格式     | `.zip`  |

---

## 3. 目录结构

```
gsv-package-{timestamp}.zip
├── config.json               # 元数据配置文件（必需）
├── models/
│   ├── {gpt}.ckpt            # GPT 模型文件（必需）
│   └── {sovits}.pth          # SoVITS 模型文件（必需）
└── reference/
    └── {audio}.wav           # 参考音频文件（必需）
```

### 示例

```
gsv-package-1718968800000.zip
├── config.json
├── models/
│   ├── gsv-v2.ckpt
│   └── gsv-v2.pth
└── reference/
    └── ref-speaker.wav
```

---

## 4. config.json 规范

### 4.1 字段定义

```typescript
interface PackageConfig {
  /** 规范版本号（当前为 "1.0"） */
  version: "1.0";

  /** ISO 8601 创建时间戳 */
  created_at: string;

  /** 模型信息 */
  model: {
    gpt: {
      filename: string;  // GPT 模型文件名（.ckpt）
      md5: string;       // 文件的 MD5 哈希值（32 位十六进制小写）
    };
    sovits: {
      filename: string;  // SoVITS 模型文件名（.pth）
      md5: string;       // 文件的 MD5 哈希值
    };
  };

  /** 参考音频信息 */
  reference: {
    audio: {
      filename: string;  // 参考音频文件名（.wav）
      md5: string;       // 文件的 MD5 哈希值
    };
    text: string;        // 参考文本内容
    language: string;    // 参考音频语种
  };

  /** 合成参数 */
  synthesis: {
    language: string;     // 合成语种
    cut_method: string;   // 切句方式
    model_version: string; // 模型版本号
  };
}
```

### 4.2 完整示例

```json
{
  "version": "1.0",
  "created_at": "2026-06-21T10:00:00.000Z",
  "model": {
    "gpt": {
      "filename": "gsv-v2.ckpt",
      "md5": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    },
    "sovits": {
      "filename": "gsv-v2.pth",
      "md5": "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7"
    }
  },
  "reference": {
    "audio": {
      "filename": "ref-speaker.wav",
      "md5": "c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8"
    },
    "text": "今天天气真好，我们一起去公园散步吧。",
    "language": "中文"
  },
  "synthesis": {
    "language": "中文",
    "cut_method": "不切",
    "model_version": "V2"
  }
}
```

### 4.3 字段说明

| 字段                 | 必需 | 说明                               |
| -------------------- | ---- | ---------------------------------- |
| `version`            | 是   | 规范版本，当前固定为 `"1.0"`        |
| `created_at`         | 是   | ISO 8601 格式，如 `2026-06-21T10:00:00.000Z` |
| `model.gpt.filename` | 是   | `.ckpt` 后缀的 GPT 模型文件         |
| `model.gpt.md5`      | 是   | 32 位十六进制 MD5 哈希，小写        |
| `model.sovits.filename` | 是 | `.pth` 后缀的 SoVITS 模型文件       |
| `model.sovits.md5`   | 是   | 同上                               |
| `reference.audio.filename` | 是 | `.wav` 后缀的参考音频文件          |
| `reference.audio.md5` | 是  | 同上                               |
| `reference.text`     | 是   | 参考音频对应的文本内容               |
| `reference.language` | 是   | 可选值：中文、英文、日文、粤语、韩语、中英混合、日英混合、多语种混合 |
| `synthesis.language` | 是   | 同上                               |
| `synthesis.cut_method` | 是 | 可选值：不切、四句一切、50字一切、中文句号切、英文句号切、标点符号切 |
| `synthesis.model_version` | 是 | 可选值：V1、V2、V3、V4、V2Pro、V2ProPlas |

---

## 5. 校验规则

### 5.1 MD5 校验

- 打包时对 `model.gpt`、`model.sovits`、`reference.audio` 三个文件分别计算 **128-bit MD5** 哈希
- 哈希值写入 `config.json` 对应字段
- 加载时可通过校验 `config.json` 中的 MD5 与文件实际哈希是否一致来判断文件完整性

### 5.2 结构校验

加载时需验证：
1. zip 内是否包含 `config.json`
2. `config.json` 中 `version` 字段是否为支持的版本
3. `model.gpt.filename` 指向的文件是否存在于 `models/` 目录且为 `.ckpt`
4. `model.sovits.filename` 指向的文件是否存在于 `models/` 目录且为 `.pth`
5. `reference.audio.filename` 指向的文件是否存在于 `reference/` 目录且为 `.wav`

---

## 6. 打包说明

- 压缩算法：DEFLATE
- 压缩级别：6（默认平衡）
- 文件名格式：`gsv-package-{timestamp}.zip`
- 目录分隔符：`/`（Unix 风格）

---

## 7. 版本历史

| 版本号 | 日期       | 变更说明             |
| ------ | ---------- | -------------------- |
| 1.0    | 2026-06-21 | 初始规范定义         |
