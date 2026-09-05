/**
 * GSV 整合包工具函数
 *
 * GSVP 格式（v1）：
 * [0:6]   GSVP 魔数 (0x475356500001)
 * [6:8]   version (uint16 LE, 1)
 * [8:10]  header_len (uint16 LE, 对齐 256)
 * [10:12] xor_key (uint16 LE)
 * [12:]   padding (0x00 至 header_len)
 * [header_len:header_len+2] entry_count (uint16 LE)
 * [entry_count 组]:
 *   [+2]    name_len (uint16 LE)
 *   [+name_len] name (UTF-8, XOR 混淆)
 *   [+4]    data_len (uint32 LE)
 *   [+data_len] data (XOR 混淆)
 */

import SparkMD5 from 'spark-md5';

// ─── 魔数定义 ──────────────────────────────────────

const MAGIC_GSVP = new Uint8Array([0x47, 0x53, 0x56, 0x50, 0x00, 0x01]);
const GSVP_HEADER_ALIGN = 256;
const GSVP_HEADER_VERSION = 1;

/** 整合包文件扩展名 */
export const GSVP_EXT = '.gsvp';

// ─── XOR 混淆 ──────────────────────────────────────

function xorObfuscate(data: Uint8Array, key: number, startOffset: number): Uint8Array {
  const out = new Uint8Array(data.length);
  for (let i = 0; i < data.length; i++) {
    out[i] = data[i] ^ ((key + startOffset + i) & 0xFF);
  }
  return out;
}

// ─── 文件哈希 ──────────────────────────────────────

function readAsArrayBuffer(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = reject;
    reader.readAsArrayBuffer(file);
  });
}

export async function computeFileHash(file: File): Promise<string> {
  const buffer = await readAsArrayBuffer(file);
  const spark = new SparkMD5.ArrayBuffer();
  spark.append(buffer);
  return spark.end();
}

// ─── 魔数操作 ──────────────────────────────────────

/** 检查文件是否以 GSVP 魔数开头 */
export function isGsvpFile(data: Uint8Array): boolean {
  for (let i = 0; i < MAGIC_GSVP.length; i++) {
    if (data[i] !== MAGIC_GSVP[i]) return false;
  }
  return true;
}

// ─── 创建整合包 ─────────────────────────────────

export interface PackageConfig {
  version: '1.0';
  created_at: string;
  compression: 'none';
  model: {
    gpt: { filename: string; md5: string };
    sovits: { filename: string; md5: string };
  };
  reference: {
    audios: { filename: string; md5: string }[];
    text: string;
    language: string;
  };
  synthesis: {
    language: string;
    cut_method: string;
    model_version: string;
  };
}

export function buildConfig(params: {
  gptFile: File; gptHash: string;
  sovitsFile: File; sovitsHash: string;
  audioFiles: { file: File; hash: string }[];
  refText: string;
  synthLang: string;
  refLang: string;
  cutMethod: string;
  modelVersion: string;
}): PackageConfig {
  return {
    version: '1.0',
    created_at: new Date().toISOString(),
    compression: 'none',
    model: {
      gpt:  { filename: params.gptFile.name,  md5: params.gptHash },
      sovits: { filename: params.sovitsFile.name, md5: params.sovitsHash },
    },
    reference: {
      audios: params.audioFiles.map((a) => ({ filename: a.file.name, md5: a.hash })),
      text: params.refText,
      language: params.refLang,
    },
    synthesis: {
      language: params.synthLang,
      cut_method: params.cutMethod,
      model_version: params.modelVersion,
    },
  };
}

/** 读取 File 为 Uint8Array */
async function readFileBytes(file: File): Promise<Uint8Array> {
  const buffer = await readAsArrayBuffer(file);
  return new Uint8Array(buffer);
}

// ─── 16 位/32 位小端写入 ────────────────────────

function le16(v: number): Uint8Array {
  const b = new Uint8Array(2);
  new DataView(b.buffer).setUint16(0, v, true);
  return b;
}

function le32(v: number): Uint8Array {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setUint32(0, v, true);
  return b;
}

/**
 * 创建 .gsvp 整合包 Blob（裸文件拼接 + XOR 混淆 + padding）
 */
export async function createPackageBlob(params: {
  config: PackageConfig;
  gptFile: File;
  sovitsFile: File;
  audioFiles: File[];
  packageName?: string;
}): Promise<{ blob: Blob; fileName: string }> {
  const { config, gptFile, sovitsFile, audioFiles } = params;
  const xorKey = Math.floor(Math.random() * 254) + 1;

  const configJson = JSON.stringify(config, null, 2);
  const configBytes = new TextEncoder().encode(configJson);
  const gptBytes = await readFileBytes(gptFile);
  const sovitsBytes = await readFileBytes(sovitsFile);
  const audioBytesList = await Promise.all(audioFiles.map(readFileBytes));

  // 构建 entries：gpt, sovits, audio..., config
  const entries: { name: string; data: Uint8Array }[] = [
    { name: gptFile.name, data: gptBytes },
    { name: sovitsFile.name, data: sovitsBytes },
    ...audioFiles.map((f, i) => ({ name: audioFiles[i].name, data: audioBytesList[i] })),
    { name: 'config.json', data: configBytes },
  ];

  // 构建数据区
  const dataParts: Uint8Array[] = [];
  let dataOffset = 0;

  // entry_count
  dataParts.push(le16(entries.length));
  dataOffset += 2;

  for (const entry of entries) {
    const nameEnc = new TextEncoder().encode(entry.name);
    // XOR 使用绝对文件位置（dataBuf 从偏移 12 开始）
    const nameXor = xorObfuscate(nameEnc, xorKey, 14 + dataOffset + 2);
    dataParts.push(le16(nameEnc.length));
    dataParts.push(nameXor);
    dataOffset += 2 + nameEnc.length;

    // 文件内容明文存储（二进制模型文件本身无特征，XOR 大文件极慢）
    dataParts.push(le32(entry.data.length));
    dataParts.push(entry.data);
    dataOffset += 4 + entry.data.length;
  }

  // 拼合数据区
  const dataBuf = new Uint8Array(dataOffset);
  let pos = 0;
  for (const p of dataParts) { dataBuf.set(p, pos); pos += p.length; }

  // 构建 header
  // magic(6) + version(2) + header_len(4) + xor_key(2) = 14
  const headerBase = 14;
  const headerTotal = headerBase + dataBuf.length;
  const padLen = (GSVP_HEADER_ALIGN - (headerTotal % GSVP_HEADER_ALIGN)) % GSVP_HEADER_ALIGN;
  const headerLen = headerTotal + padLen;

  const header = new Uint8Array(headerLen);
  let off = 0;
  header.set(MAGIC_GSVP, off); off += 6;
  header.set(le16(GSVP_HEADER_VERSION), off); off += 2;
  header.set(le16(headerLen), off); off += 2;
  header.set(le16(xorKey), off); off += 2;
  // 数据区填充到 header 尾部
  header.set(dataBuf, off);

  return {
    blob: new Blob([header], { type: 'application/octet-stream' }),
    fileName: `${params.packageName?.trim() || 'gsv-package'}${GSVP_EXT}`,
  };
}

// ─── 载入整合包 ─────────────────────────────────

export interface UnpackedPackage {
  config: PackageConfig;
  files: {
    gpt: Uint8Array;
    sovits: Uint8Array;
    audioList: { name: string; data: Uint8Array }[];
  };
}

/**
 * 载入整合包（魔数验证 + 解析 + XOR 还原）
 */
export async function loadPackage(file: File): Promise<UnpackedPackage> {
  const bytes = new Uint8Array(await readAsArrayBuffer(file));

  // 1. 检查魔数
  if (!isGsvpFile(bytes)) {
    throw new Error('无效的整合包文件：魔数不匹配');
  }

  // 2. 解析 header
  const version = new DataView(bytes.buffer, 6, 2).getUint16(0, true);
  const headerLen = new DataView(bytes.buffer, 8, 4).getUint32(0, true);
  const xorKey = new DataView(bytes.buffer, 12, 2).getUint16(0, true);

  if (version !== GSVP_HEADER_VERSION) {
    throw new Error(`不支持的版本: ${version}`);
  }

  // 3. 解析数据区（数据从偏移 14 开始）
  let off = 14;
  const entryCount = new DataView(bytes.buffer, off, 2).getUint16(0, true);
  off += 2;

  let gpt: { name: string; data: Uint8Array } | null = null;
  let sovits: { name: string; data: Uint8Array } | null = null;
  const audioList: { name: string; data: Uint8Array }[] = [];
  let config: PackageConfig | null = null;

  for (let e = 0; e < entryCount; e++) {
    const nameLen = new DataView(bytes.buffer, off, 2).getUint16(0, true);
    off += 2;
    const nameEnc = bytes.slice(off, off + nameLen);
    const nameDec = xorObfuscate(nameEnc, xorKey, off);  // off = name 数据起始
    off += nameLen;
    const name = new TextDecoder('utf-8', { fatal: false }).decode(nameDec);

    const dataLen = new DataView(bytes.buffer, off, 4).getUint32(0, true);
    off += 4;
    const dataDec = bytes.slice(off, off + dataLen);  // 文件内容明文存储
    off += dataLen;

    if (name === 'config.json') {
      config = JSON.parse(new TextDecoder('utf-8', { fatal: false }).decode(dataDec));
    } else if (!gpt) {
      gpt = { name, data: dataDec };
    } else if (!sovits) {
      sovits = { name, data: dataDec };
    } else {
      audioList.push({ name, data: dataDec });
    }
  }

  if (!gpt || !sovits) {
    throw new Error('整合包缺少模型文件');
  }

  return {
    config: config || { version: '1.0', created_at: '', compression: 'none', model: { gpt: { filename: '', md5: '' }, sovits: { filename: '', md5: '' } }, reference: { audios: [], text: '', language: '' }, synthesis: { language: '', cut_method: '', model_version: '' } },
    files: { gpt: gpt.data, sovits: sovits.data, audioList },
  };
}
