#!/usr/bin/env python3
"""
GSV 整合包管理后端 API Server

全部核心逻辑由后端实现（裸文件+XOR 混淆、MD5 校验等），
浏览器仅负责 UI 渲染和 API 调用。

运行方式：
  runtime/venv/Scripts/python runtime/server.py
"""

import os, re, json, shutil, struct, threading, io, uuid, time, random
from pathlib import Path
from hashlib import md5
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS, cross_origin
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# ─── 配置 ──────────────────────────────────────────

# 最大上传 10GB（模型文件可能很大）
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024

BASE_DIR = os.getenv('GSV_PACKAGES_DIR', os.path.join(os.path.dirname(__file__), 'packages'))
DOWNLOAD_DIR = os.getenv('GSV_DOWNLOAD_DIR', os.path.join(os.path.dirname(__file__), 'downloads'))
MODELS_ROOT = os.getenv('GSV_MODELS_ROOT', 'D:\\Desktop\\GPT-SoVITS\\GSV测试\\text')

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ─── 进度追踪 ──────────────────────────────────────
_task_progress: dict[str, dict] = {}  # task_id -> { progress, status, error, fileName }
_task_lock = threading.Lock()

def set_progress(task_id: str, progress: int, status: str = 'processing', **extra):
    with _task_lock:
        _task_progress[task_id] = {'progress': progress, 'status': status, **extra}

def get_progress(task_id: str) -> dict:
    with _task_lock:
        return _task_progress.get(task_id, {'progress': 0, 'status': 'unknown'})

# ─── 魔数 ──────────────────────────────────────────

MAGIC_GSVP = bytes([0x47, 0x53, 0x56, 0x50, 0x00, 0x01])  # "GSVP\0\1"

GSVP_HEADER_VERSION = 1
GSVP_HEADER_ALIGN = 256  # header 对齐到 256 字节，跳过填充快速定位数据区

# ─── XOR 混淆 ──────────────────────────────────────

def xor_obfuscate(data: bytes, key: int, start_offset: int = 0) -> bytes:
    """滚动 XOR：每个字节 XOR (key + (offset+i)) & 0xFF，仅用于小数据（文件名/config）"""
    return bytes((b ^ ((key + start_offset + i) & 0xFF)) for i, b in enumerate(data))

xor_deobfuscate = xor_obfuscate  # XOR 是对称的

# ─── GSVP 格式 ─────────────────────────────────────

def build_gsvp(config: dict, files: dict, xor_key: int, progress_cb=None) -> bytes:
    """
    构建 .gsvp 包（裸文件 + XOR 混淆 + padding 填充）
    files: { 'gpt': (bytes, filename), 'sovits': (bytes, filename), 'audios': [(bytes, filename), ...] }
    progress_cb: optional callback(bytes_processed, total_bytes, current_file)
    """
    entries = [
        ('gpt', files['gpt'][0], files['gpt'][1]),
        ('sovits', files['sovits'][0], files['sovits'][1]),
    ]
    for adata, aname in files['audios']:
        entries.append(('audio', adata, aname))
    config_json = json.dumps(config, ensure_ascii=False, indent=2).encode('utf-8')
    entries.append(('config', config_json, 'config.json'))

    total = sum(len(d) for _, d, _ in entries)

    # 预计算 data_buf 总大小，预分配避免 realloc 拷贝 155MB
    data_size = 2  # entry_count
    for _, edata, ename in entries:
        data_size += 2 + len(ename.encode('utf-8')) + 4 + len(edata)

    data_buf = bytearray(data_size)
    writer = memoryview(data_buf)
    pos = 0
    writer[pos:pos+2] = struct.pack('<H', len(entries)); pos += 2
    processed = 0

    for etype, edata, ename in entries:
        ename_enc = ename.encode('utf-8')
        name_data_off = 14 + pos + 2  # 使用 pos 而非 len(data_buf)
        ename_xor = xor_obfuscate(ename_enc, xor_key, name_data_off)
        writer[pos:pos+2] = struct.pack('<H', len(ename_enc)); pos += 2
        writer[pos:pos+len(ename_xor)] = ename_xor; pos += len(ename_xor)
        writer[pos:pos+4] = struct.pack('<I', len(edata)); pos += 4
        writer[pos:pos+len(edata)] = edata; pos += len(edata)
        processed += len(edata)
        if progress_cb:
            progress_cb(processed, total, ename)

    # 构建 header（对齐到 GSVP_HEADER_ALIGN）
    header_base = 6 + 2 + 4 + 2  # magic(6) + version(2) + header_len(4) + xor_key(2)
    header_total = header_base + len(data_buf)
    pad_needed = (GSVP_HEADER_ALIGN - (header_total % GSVP_HEADER_ALIGN)) % GSVP_HEADER_ALIGN
    header_len = header_total + pad_needed

    buf = bytearray()
    buf += MAGIC_GSVP
    buf += struct.pack('<H', GSVP_HEADER_VERSION)
    buf += struct.pack('<I', header_len)
    buf += struct.pack('<H', xor_key)
    buf += data_buf  # 直接追加数据，避免预分配 230MB 零填充 + 二次拷贝
    # padding 对齐（仅几百字节）
    pad_len = header_len - len(buf)
    if pad_len > 0:
        buf += b'\x00' * pad_len
    return buf  # 返回 bytearray，避免 bytes() 产生第三次拷贝


def parse_gsvp(data: bytes, debug: bool = False) -> dict:
    """解析 .gsvp 包，返回 {'config': dict, 'files': { 'gpt': (bytes, name), 'sovits': (bytes, name), 'audios': [(bytes, name), ...] } }"""
    if data[:6] != MAGIC_GSVP:
        raise ValueError('无效的整合包文件：魔数不匹配')

    # 尝试两种 header_len 格式:
    #   A) uint16 (前端格式): [8]header_len(2) + [10]xor_key(2) → data_offset=12
    #   B) uint32 (后端格式): [8]header_len(4) + [12]xor_key(2) → data_offset=14
    version = struct.unpack_from('<H', data, 6)[0]

    if version == GSVP_HEADER_VERSION:
        # 标准格式: 直接按后端格式(uint32)解析
        _header_len = struct.unpack_from('<I', data, 8)[0]
        xor_key = struct.unpack_from('<H', data, 12)[0]
        offset = 14
    elif version == 1024:
        # 前端生成的文件有已知 bug。尝试两个可能的 data_offset:
        #   data_offset=12 (前端实际写入位置)
        #   data_offset=14 (前端 headerBase bug 导致的偏移)
        # 取 entry_count 合理的那个。
        ec12 = struct.unpack_from('<H', data, 12)[0]
        ec14 = struct.unpack_from('<H', data, 14)[0]
        # 合理的 entry_count 应在 2-5000 之间
        if 2 <= ec14 <= 5000:
            xor_key = struct.unpack_from('<H', data, 12)[0]
            offset = 14
            if debug:
                print(f'  [DEBUG] 使用 data_offset=14 (entry_count={ec14})', flush=True)
        elif 2 <= ec12 <= 5000:
            xor_key = struct.unpack_from('<H', data, 10)[0]
            offset = 12
            if debug:
                print(f'  [DEBUG] 使用 data_offset=12 (entry_count={ec12})', flush=True)
        else:
            raise ValueError(f'无法确定 header 格式: ec12={ec12} ec14={ec14}')
        if debug:
            print(f'  [DEBUG] 非标准 version={version} 已兼容处理', flush=True)
    else:
        raise ValueError(f'不支持的版本: {version} (期望 {GSVP_HEADER_VERSION})')

    entry_count = struct.unpack_from('<H', data, offset)[0]
    offset += 2

    gpt = None
    sovits = None
    audios = []
    config = None

    for _ in range(entry_count):
        name_len = struct.unpack_from('<H', data, offset)[0]
        offset += 2
        name_enc = data[offset:offset + name_len]
        offset += name_len
        data_len = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        file_data = data[offset:offset + data_len]
        offset += data_len

        # 解密
        name = xor_deobfuscate(name_enc, xor_key, offset - data_len - name_len - 4).decode('utf-8', errors='replace')
        fdata = file_data  # 文件内容明文存储

        if name == 'config.json':
            config = json.loads(fdata.decode('utf-8'))
        elif gpt is None:
            gpt = (fdata, name)
        elif sovits is None:
            sovits = (fdata, name)
        else:
            audios.append((fdata, name))

    if gpt is None or sovits is None:
        raise ValueError('整合包缺少模型文件')
    return {'config': config or {}, 'files': {'gpt': gpt, 'sovits': sovits, 'audios': audios}}


def validate_gsvp(data: bytes) -> bytes:
    """验证 GSVP 魔数（兼容旧版调用，直接返回原始数据）"""
    if data[:6] != MAGIC_GSVP:
        raise ValueError('无效的整合包文件：魔数不匹配')
    return data


def patch_to_gsvp(data: bytes) -> bytes:
    """placeholder：保留旧接口兼容"""
    return data


def create_gsvp(config: dict, files: dict, progress_cb=None) -> bytes:
    """创建 .gsvp 包（入口，自动生成随机 XOR key）"""
    xor_key = random.randint(1, 254)
    return build_gsvp(config, files, xor_key, progress_cb)


def extract_gsvp(data: bytes, target_dir: str, debug: bool = False):
    """解压 .gsvp 包到 target_dir"""
    parsed = parse_gsvp(data, debug=debug)
    os.makedirs(target_dir, exist_ok=True)

    # 写 GPT
    gpt_data, gpt_name = parsed['files']['gpt']
    (Path(target_dir) / gpt_name).write_bytes(gpt_data)

    # 写 SoVITS
    sovits_data, sovits_name = parsed['files']['sovits']
    (Path(target_dir) / sovits_name).write_bytes(sovits_data)

    # 写音频
    audio_dir = Path(target_dir) / 'reference_audios'
    audio_dir.mkdir(parents=True, exist_ok=True)
    for adata, aname in parsed['files']['audios']:
        (audio_dir / aname).write_bytes(adata)

    # 写 config
    cfg = parsed['config']
    if cfg:
        (Path(target_dir) / 'config.json').write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


def compute_md5(data: bytes) -> str:
    return md5(data).hexdigest()


def read_file_bytes(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read()


def find_packages(base: str) -> list[dict]:
    """扫描整合包目录，返回所有包的信息"""
    results = []
    base_path = Path(base)
    if not base_path.exists():
        return results
    for item in base_path.iterdir():
        if item.is_dir():
            cfg_file = item / 'config.json'
            if cfg_file.exists():
                try:
                    cfg = json.loads(cfg_file.read_text('utf-8'))
                except Exception:
                    continue
                ref = cfg.get('reference', {})
                syn = cfg.get('synthesis', {})
                audio_count = 0
                ref_dir = item / 'reference_audios'
                if ref_dir.is_dir():
                    audio_count = sum(1 for f in ref_dir.rglob('*') if f.is_file() and f.suffix.lower() in ('.wav', '.mp3', '.flac'))
                results.append({
                    'name': item.name, 'path': str(item), 'type': 'extracted',
                    'refLang': ref.get('language', '-'),
                    'modelVersion': syn.get('model_version', '-'),
                    'cutMethod': syn.get('cut_method', '-'),
                    'audioCount': audio_count,
                    'packageType': cfg.get('package_type', 'standard'),
                    'emotionTags': ref.get('emotion_tags', []),
                    'refText': ref.get('text', '') or syn.get('ref_text', ''),
                })
        elif item.suffix.lower() == '.gsvp':
            meta_file = item.with_suffix('.gsvp.meta.json')
            meta = {}
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text('utf-8'))
                except Exception:
                    pass
            results.append({
                'name': item.stem, 'path': str(item), 'type': 'gsvp',
                'refLang': meta.get('refLang', '-'),
                'modelVersion': meta.get('modelVersion', '-'),
                'cutMethod': meta.get('cutMethod', '-'),
                'audioCount': meta.get('audioCount', 0),
                'packageType': meta.get('packageType', 'standard'),
                'emotionTags': meta.get('emotionTags', []),
                'refText': meta.get('refText', ''),
            })
    return results


# ─── API 路由 ──────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '2.0'})

# ── 创建整合包 ────────────────────────────────────

@app.route('/packages/create', methods=['OPTIONS', 'POST'])
@cross_origin()
def create_package():
    """
    创建整合包（全部后端处理）
    接收: multipart/form-data
      - gpt:       .ckpt 文件
      - sovits:    .pth 文件
      - audios:    .wav 文件（可多个，字段名 audios）
      - meta:      JSON 字符串 { refLang, cutMethod, modelVersion, refText, packageName }
    返回: .gsvp 文件下载
    """
    try:
        gpt_file = request.files.get('gpt')
        sovits_file = request.files.get('sovits')
        audio_files = request.files.getlist('audios')
        meta_str = request.form.get('meta', '{}')
        meta = json.loads(meta_str)

        if not gpt_file or not sovits_file:
            return jsonify({'success': False, 'error': '请上传 GPT 和 SoVITS 模型文件'}), 400
        if not audio_files:
            return jsonify({'success': False, 'error': '请上传至少一个参考音频文件'}), 400
        ref_text = meta.get('refText', '').strip()
        if not ref_text:
            return jsonify({'success': False, 'error': '请输入参考文本'}), 400

        gpt_data = gpt_file.read()
        sovits_data = sovits_file.read()
        audio_data_list = [(af.read(), secure_filename(af.filename or f'ref_audio_{i+1}.wav'))
                           for i, af in enumerate(audio_files)]

        # 计算 MD5
        gpt_md5 = compute_md5(gpt_data)
        sovits_md5 = compute_md5(sovits_data)
        audio_md5_list = [compute_md5(ad[0]) for ad in audio_data_list]

        # 构建 config
        config = {
            'version': '1.0',
            'created_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'compression': '7z',
            'package_type': meta.get('packageType', 'standard'),
            'model': {
                'gpt':    {'filename': secure_filename(gpt_file.filename or 'gpt.ckpt'),    'md5': gpt_md5},
                'sovits': {'filename': secure_filename(sovits_file.filename or 'sovits.pth'), 'md5': sovits_md5},
            },
            'reference': {
                'audios': [{'filename': ad[1], 'md5': audio_md5_list[i]} for i, ad in enumerate(audio_data_list)],
                'text': ref_text,
                'language': meta.get('refLang', '中文'),
                'emotion_tags': meta.get('emotionTags', []),
            },
            'synthesis': {
                'language': meta.get('refLang', '中文'),
                'cut_method': meta.get('cutMethod', '不切'),
                'model_version': meta.get('modelVersion', ''),
            },
        }

        # 创建 .gsvp
        gsvp_bytes = create_gsvp(config, {
            'gpt': (gpt_data, secure_filename(gpt_file.filename or 'gpt.ckpt')),
            'sovits': (sovits_data, secure_filename(sovits_file.filename or 'sovits.pth')),
            'audios': audio_data_list,
        })

        pkg_name = (meta.get('packageName', '').strip() or 'gsv-package') + '.gsvp'

        # 复制 .gsvp 到系统 Downloads 文件夹
        downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        download_path = os.path.join(downloads_dir, pkg_name)
        try:
            with open(download_path, 'wb') as f:
                f.write(gsvp_bytes)
        except Exception as ex:
            print(f'保存到下载目录失败: {ex}')

        # 同步解压到 packages/<name>/
        try:
            target_dir = os.path.join(BASE_DIR, Path(pkg_name).stem)
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
            extract_gsvp(gsvp_bytes, target_dir)
        except Exception as ex:
            print(f'同步解压失败: {ex}')

        # 返回 JSON（不再返回文件流，.gsvp 已保存到下载目录）
        pkg_stem = Path(pkg_name).stem
        return jsonify({
            'success': True, 'name': pkg_stem,
            'downloadPath': os.path.abspath(download_path),
            'meta': {
                'refLang': meta.get('refLang', '-'),
                'cutMethod': meta.get('cutMethod', '-'),
                'modelVersion': meta.get('modelVersion', '-'),
                'audioCount': len(audio_files),
                'refLangs': meta.get('refLangs', []),
            },
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/packages/create-from-paths', methods=['OPTIONS', 'POST'])
@cross_origin()
def create_from_paths():
    """
    创建整合包（异步，返回 task_id，前端轮询进度）
    接收: JSON { gpt_path, sovits_path, audio_paths[], meta: {...} }
    返回: JSON { task_id }
    """
    data = request.get_json() or {}
    meta = data.get('meta', {})
    gpt_path = data.get('gpt_path', '')
    sovits_path = data.get('sovits_path', '')
    audio_paths = data.get('audio_paths', [])

    if not gpt_path or not sovits_path:
        return jsonify({'success': False, 'error': '缺少模型文件路径'}), 400
    if not audio_paths:
        return jsonify({'success': False, 'error': '缺少参考音频路径'}), 400
    ref_text = meta.get('refText', '').strip()
    if not ref_text:
        return jsonify({'success': False, 'error': '请输入参考文本'}), 400

    task_id = uuid.uuid4().hex[:12]
    set_progress(task_id, 0, 'processing')

    def _build(args):
        _gpt_path, _sovits_path, _audio_paths, _meta = args
        try:
            total_steps = 6
            step = 0

            # 验证所有文件存在
            missing = [p for p in [_gpt_path, _sovits_path] if not os.path.isfile(p)]
            missing += [p for p in _audio_paths if not os.path.isfile(p)]
            if missing:
                raise FileNotFoundError(f'文件不存在: {missing[0]}')

            # 计算总字节（读取前通过文件大小估算）
            total_bytes = os.path.getsize(_gpt_path) + os.path.getsize(_sovits_path) + sum(os.path.getsize(p) for p in _audio_paths)

            def sp(pct, status='processing', **kw):
                """set_progress + 主动释放 GIL，确保 Flask 进度线程不被饿死"""
                set_progress(task_id, pct, status, **kw)
                time.sleep(0)

            # 1. 读取文件 (0 → 20)
            sp(0, 'reading', totalBytes=total_bytes, processedBytes=0)
            gpt_data = read_file_bytes(_gpt_path); step += 1
            sp(int(step / total_steps * 100), 'reading', totalBytes=total_bytes, processedBytes=os.path.getsize(_gpt_path))
            sovits_data = read_file_bytes(_sovits_path); step += 1
            p_sofar = os.path.getsize(_gpt_path) + os.path.getsize(_sovits_path)
            sp(int(step / total_steps * 100), 'reading', totalBytes=total_bytes, processedBytes=p_sofar)
            audio_data_list = [(read_file_bytes(p), os.path.basename(p)) for p in _audio_paths]; step += 1
            sp(int(step / total_steps * 100), 'reading', totalBytes=total_bytes, processedBytes=total_bytes)

            gpt_fn = os.path.basename(_gpt_path)
            sovits_fn = os.path.basename(_sovits_path)

            total_bytes = len(gpt_data) + len(sovits_data) + sum(len(a[0]) for a in audio_data_list)
            processed_base = [0]  # mutable counter for non-compressing stages

            # 2. 计算 MD5 (20 → 30)
            sp(20, 'hashing', totalBytes=total_bytes, processedBytes=0)
            gpt_md5 = compute_md5(gpt_data)
            sp(25, 'hashing', totalBytes=total_bytes, processedBytes=len(gpt_data))
            sovits_md5 = compute_md5(sovits_data)
            audio_md5_list = [compute_md5(ad[0]) for ad in audio_data_list]
            processed_base[0] = len(gpt_data) + len(sovits_data) + sum(len(ad[0]) for ad in audio_data_list)
            sp(30, 'hashing', totalBytes=total_bytes, processedBytes=processed_base[0])

            # 3. 构建 config
            config = {
                'version': '1.0',
                'created_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'compression': '7z',
                'package_type': _meta.get('packageType', 'standard'),
                'model': {
                    'gpt': {'filename': secure_filename(gpt_fn), 'md5': gpt_md5},
                    'sovits': {'filename': secure_filename(sovits_fn), 'md5': sovits_md5},
                },
                'reference': {
                    'audios': [{'filename': ad[1], 'md5': audio_md5_list[i]} for i, ad in enumerate(audio_data_list)],
                    'text': _meta.get('refText', '').strip(),
                    'language': _meta.get('refLang', '中文'),
                    'emotion_tags': _meta.get('emotionTags', []),
                },
                'synthesis': {
                    'language': _meta.get('refLang', '中文'),
                    'cut_method': _meta.get('cutMethod', '不切'),
                    'model_version': _meta.get('modelVersion', ''),
                },
            }
            sp(35)

            # 4. 7z 打包 (35 → 70)
            sp(35, 'compressing', totalBytes=total_bytes, processedBytes=0)
            start_time = time.time()
            total_bytes = total_bytes  # reuse from earlier
            saved_progress = [35]

            def on_pack(processed, total, current_file):
                pct = 35 + int(processed / total * 35) if total > 0 else 50
                if pct > saved_progress[0]:
                    saved_progress[0] = pct
                    elapsed = time.time() - start_time
                    speed_bps = processed / elapsed if elapsed > 0 else 0
                    remaining = (total - processed) / speed_bps if speed_bps > 0 else 0
                    set_progress(task_id, pct, 'compressing',
                                 totalBytes=total, processedBytes=processed, speedBps=int(speed_bps),
                                 etaSecs=int(remaining), currentFile=current_file)
                time.sleep(0)  # 释放 GIL，让 Flask 进度线程有机会执行

            gsvp_bytes = create_gsvp(config, {
                'gpt': (gpt_data, secure_filename(gpt_fn)),
                'sovits': (sovits_data, secure_filename(sovits_fn)),
                'audios': audio_data_list,
            }, progress_cb=on_pack)
            sp(70)

            pkg_name = (_meta.get('packageName', '').strip() or 'gsv-package') + '.gsvp'
            downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
            download_path = os.path.join(downloads_dir, pkg_name)

            # 5. 后台保存到下载文件夹 + 同步解压
            sp(75, 'saving', totalBytes=total_bytes, processedBytes=total_bytes)
            try:
                # 保存到 Downloads 文件夹
                with open(download_path, 'wb') as f:
                    f.write(gsvp_bytes)
                # 同步解压到 packages/<name>/
                td = os.path.join(BASE_DIR, Path(pkg_name).stem)
                if os.path.exists(td): shutil.rmtree(td)
                extract_gsvp(gsvp_bytes, td)
                sp(100, 'done', fileName=pkg_name, filePath=os.path.abspath(download_path), totalBytes=total_bytes, processedBytes=total_bytes)
            except Exception as ex:
                print(f'保存/解压失败: {ex}')
        except Exception as ex:
            import traceback; traceback.print_exc()
            sp(-1, 'error', error=str(ex))

    threading.Thread(target=_build, args=((gpt_path, sovits_path, audio_paths, meta),), daemon=True).start()
    return jsonify({'task_id': task_id})


@app.route('/packages/progress', methods=['GET'])
@cross_origin()
def package_progress():
    """轮询创建进度"""
    task_id = request.args.get('task_id', '')
    if not task_id:
        return jsonify({'progress': 0, 'status': 'unknown'})
    return jsonify(get_progress(task_id))


@app.route('/packages/download', methods=['GET'])
@cross_origin()
def download_pkg():
    """下载已创建的 .gsvp 文件"""
    name = request.args.get('name', '')
    file_path = os.path.join(BASE_DIR, name)
    if not os.path.isfile(file_path):
        return jsonify({'success': False, 'error': '文件不存在'}), 404
    return send_file(file_path, mimetype='application/octet-stream', as_attachment=True, download_name=name)


# ── 上传 & 载入整合包 ──────────────────────────────

@app.route('/packages/upload', methods=['OPTIONS', 'POST'])
@cross_origin()
def upload_package():
    """上传 .gsvp 文件 → 验证魔数 → 返回元数据 → 后台解压"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未上传文件'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'success': False, 'error': '文件名为空'}), 400
    safe_name = secure_filename(f.filename)
    dest = os.path.join(BASE_DIR, safe_name)
    f.save(dest)
    # 使用原始文件名的 stem 作为显示名（secure_filename 会破坏中文等非 ASCII 字符）
    raw_stem = Path(f.filename).stem
    name = raw_stem if raw_stem else Path(safe_name).stem

    # 验证魔数
    with open(dest, 'rb') as fh:
        head = fh.read(len(MAGIC_GSVP))
    if head != MAGIC_GSVP:
        os.remove(dest)
        return jsonify({'success': False, 'error': '无效的整合包文件：魔数不匹配'}), 400

    # 读取元数据（从 config.json）
    meta_data = {'refLang': '-', 'modelVersion': '-', 'cutMethod': '-', 'audioCount': 0, 'packageType': 'standard', 'emotionTags': [], 'refText': ''}
    try:
        gsvp_data = read_file_bytes(dest)
        extract_gsvp(gsvp_data, os.path.join(BASE_DIR, '__tmp_meta__'))
        tmp_cfg = Path(BASE_DIR) / '__tmp_meta__' / 'config.json'
        if tmp_cfg.exists():
            cfg = json.loads(tmp_cfg.read_text('utf-8'))
            shutil.rmtree(Path(BASE_DIR) / '__tmp_meta__')
            ref = cfg.get('reference', {})
            syn = cfg.get('synthesis', {})
            meta_data = {
                'refLang': ref.get('language', '-'),
                'modelVersion': syn.get('model_version', '-'),
                'cutMethod': syn.get('cut_method', '-'),
                'audioCount': len(ref.get('audios', [])),
                'packageType': cfg.get('package_type', 'standard'),
                'emotionTags': ref.get('emotion_tags', []),
            }
    except Exception:
        pass

    # 后台完整解压
    def _extract_pkg():
        try:
            target = os.path.join(BASE_DIR, name)
            if os.path.exists(target):
                shutil.rmtree(target)
            extract_gsvp(read_file_bytes(dest), target)
        except Exception as ex:
            print(f'后台解压失败: {ex}')
    threading.Thread(target=_extract_pkg, daemon=True).start()

    return jsonify({
        'success': True, 'path': os.path.abspath(dest), 'name': name,
        'loading': True, 'meta': meta_data,
    })


@app.route('/packages/search')
def search_packages():
    entries = find_packages(BASE_DIR)
    return jsonify(entries)


@app.route('/packages/config', methods=['GET'])
def get_package_config():
    """获取整合包的 config.json 数据"""
    name = request.args.get('name', '')
    if not name:
        return jsonify({'error': '请提供包名'}), 400
    cfg_path = os.path.join(BASE_DIR, name, 'config.json')
    if os.path.isfile(cfg_path):
        try:
            cfg = json.loads(open(cfg_path, 'r', encoding='utf-8').read())
            ref = cfg.get('reference', {})
            return jsonify({'refText': ref.get('text', ''), 'emotionTags': ref.get('emotion_tags', [])})
        except Exception:
            return jsonify({'error': '读取配置失败'}), 500
    return jsonify({'error': '配置不存在'}), 404


@app.route('/packages/delete', methods=['POST'])
def delete_package():
    data = request.get_json() or {}
    name = data.get('name', '')
    if not name:
        return jsonify({'success': False, 'error': '请提供包名'}), 400
    for ext in ('.gsvp', '.gsvp.meta.json'):
        p = os.path.join(BASE_DIR, f'{name}{ext}')
        if os.path.isfile(p):
            os.remove(p)
    d = os.path.join(BASE_DIR, name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    return jsonify({'success': True})


# ── 磁盘导入（跳过HTTP上传，后端直接读盘） ──────────

# 尝试导入 tkinter 用于原生文件对话框
try:
    import tkinter as tk
    from tkinter import filedialog
    HAS_TK = True
except ImportError:
    HAS_TK = False


@app.route('/packages/file-picker', methods=['GET'])
@cross_origin()
def file_picker():
    """
    后端打开原生 OS 文件选择对话框，返回用户选择的文件路径。
    支持查询参数 ?ext=ckpt|pth|wav|gsvp 限定文件类型，默认 .gsvp。

    返回: JSON { success, path } 或 { success: false, error }
    """
    ext = request.args.get('ext', 'gsvp').lstrip('.')
    ext_map = {
        'ckpt': ('GPT 模型文件', '*.ckpt'),
        'pth':  ('SoVITS 模型文件', '*.pth'),
        'wav':  ('音频文件', '*.wav;*.mp3;*.flac;*.ogg;*.m4a'),
        'gsvp': ('整合包文件', '*.gsvp'),
    }
    label, pattern = ext_map.get(ext, ext_map['gsvp'])
    filter_ctypes = f'{label} ({pattern})\0{pattern}\0所有文件 (*.*)\0*.*\0'
    filter_tk = [(label, pattern), ('All Files', '*.*')]
    title = f'选择 {label}'

    if not HAS_TK:
        return jsonify({'success': False, 'error': '当前环境不支持原生文件对话框'}), 400
    try:
        # 方式1: 尝试用 ctypes Windows API 打开原生高 DPI 对话框
        try:
            import ctypes
            from ctypes import wintypes
            # 启用高 DPI
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

            # 构造 OPENFILENAME 结构体
            class OPENFILENAME(ctypes.Structure):
                _fields_ = [
                    ('lStructSize', wintypes.DWORD),
                    ('hwndOwner', wintypes.HWND),
                    ('hInstance', wintypes.HINSTANCE),
                    ('lpstrFilter', wintypes.LPCWSTR),
                    ('lpstrCustomFilter', wintypes.LPWSTR),
                    ('nMaxCustFilter', wintypes.DWORD),
                    ('nFilterIndex', wintypes.DWORD),
                    ('lpstrFile', wintypes.LPWSTR),
                    ('nMaxFile', wintypes.DWORD),
                    ('lpstrFileTitle', wintypes.LPWSTR),
                    ('nMaxFileTitle', wintypes.DWORD),
                    ('lpstrInitialDir', wintypes.LPCWSTR),
                    ('lpstrTitle', wintypes.LPCWSTR),
                    ('Flags', wintypes.DWORD),
                    ('nFileOffset', wintypes.WORD),
                    ('nFileExtension', wintypes.WORD),
                    ('lpstrDefExt', wintypes.LPCWSTR),
                    ('lCustData', wintypes.LPARAM),
                    ('lpfnHook', wintypes.LPVOID),
                    ('lpTemplateName', wintypes.LPCWSTR),
                    ('pvReserved', wintypes.LPVOID),
                    ('dwReserved', wintypes.DWORD),
                    ('FlagsEx', wintypes.DWORD),
                ]

            buf = ctypes.create_unicode_buffer(260)
            ofn = OPENFILENAME(
                lStructSize=ctypes.sizeof(OPENFILENAME),
                hwndOwner=None,
                lpstrFilter=filter_ctypes,
                lpstrFile=buf,
                nMaxFile=260,
                lpstrTitle=title,
                Flags=0x00000800 | 0x00001000,  # OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
            )
            if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
                path = buf.value
                if path:
                    return jsonify({'success': True, 'path': path})
        except Exception:
            pass

        # 方式2: 回退到 tkinter 对话框
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askopenfilename(
            title=title,
            filetypes=filter_tk,
        )
        root.destroy()
        if not path:
            return jsonify({'success': False, 'error': '用户取消了选择'}), 400
        return jsonify({'success': True, 'path': path})
    except Exception as e:
        return jsonify({'success': False, 'error': f'打开文件对话框失败: {e}'}), 500

@app.route('/packages/import', methods=['OPTIONS', 'POST'])
@cross_origin()
def import_package():
    """
    从服务器本地路径导入 .gsvp 文件，跳过浏览器上传。
    接收: JSON { path: "/path/to/model.gsvp" }
    返回: JSON { success, name, meta }
    后台自动解压到 packages/ 目录。
    优化：只读魔数验证，用 shutil.copy2 替代全量读入内存。
    """
    data = request.get_json() or {}
    src_path = data.get('path', '')
    if not src_path or not os.path.isfile(src_path):
        return jsonify({'success': False, 'error': '文件不存在'}), 400
    if not src_path.lower().endswith('.gsvp'):
        return jsonify({'success': False, 'error': '仅支持 .gsvp 文件'}), 400

    raw_name = Path(src_path).stem
    dest_name = secure_filename(raw_name) + '.gsvp'
    dest = os.path.join(BASE_DIR, dest_name)

    # 只读魔数验证（6 字节），避免全量读入 1GB 内存
    try:
        with open(src_path, 'rb') as fh:
            magic = fh.read(len(MAGIC_GSVP))
    except Exception as e:
        return jsonify({'success': False, 'error': f'读取失败: {e}'}), 400
    if magic != MAGIC_GSVP:
        return jsonify({'success': False, 'error': '无效的整合包文件：魔数不匹配'}), 400

    # 用 shutil.copy2 复制文件（操作系统级优化，比 read+write 快）
    try:
        shutil.copy2(src_path, dest)
    except Exception as e:
        return jsonify({'success': False, 'error': f'复制失败: {e}'}), 500

    # 从目标路径读取元数据（只读 config.json 所在的少量数据）
    meta_data = {'refLang': '-', 'modelVersion': '-', 'cutMethod': '-', 'audioCount': 0, 'packageType': 'standard', 'emotionTags': [], 'refText': ''}
    try:
        gsvp_data = read_file_bytes(dest)
        extract_gsvp(gsvp_data, os.path.join(BASE_DIR, '__tmp_meta__'))
        tmp_cfg = Path(BASE_DIR) / '__tmp_meta__' / 'config.json'
        if tmp_cfg.exists():
            cfg = json.loads(tmp_cfg.read_text('utf-8'))
            shutil.rmtree(Path(BASE_DIR) / '__tmp_meta__')
            ref = cfg.get('reference', {})
            syn = cfg.get('synthesis', {})
            meta_data = {
                'refLang': ref.get('language', '-'),
                'modelVersion': syn.get('model_version', '-'),
                'cutMethod': syn.get('cut_method', '-'),
                'audioCount': len(ref.get('audios', [])),
                'packageType': cfg.get('package_type', 'standard'),
                'emotionTags': ref.get('emotion_tags', []),
                'refText': ref.get('text', ''),
            }
    except Exception:
        pass

    # 保存元数据
    Path(dest).with_suffix('.gsvp.meta.json').write_text(
        json.dumps(meta_data, ensure_ascii=False), encoding='utf-8')

    # 后台完整解压
    def _extract_pkg():
        try:
            target = os.path.join(BASE_DIR, raw_name)
            if os.path.exists(target):
                shutil.rmtree(target)
            extract_gsvp(read_file_bytes(dest), target)
        except Exception as ex:
            print(f'后台解压失败: {ex}')
    threading.Thread(target=_extract_pkg, daemon=True).start()

    return jsonify({
        'success': True, 'name': raw_name, 'path': os.path.abspath(dest),
        'loading': True, 'meta': meta_data,
    })


# ── 文件扫描 ──────────────────────────────────────

@app.route('/files/scan-mates', methods=['POST'])
def scan_mates():
    """扫描 MODELS_ROOT 查找配套文件"""
    data = request.get_json() or {}
    base_name = data.get('base_name') or ''  # 空字符串 = 匹配所有文件

    raw_dir = data.get('dir', '') or MODELS_ROOT
    if os.path.isfile(raw_dir):
        dir_path = os.path.dirname(raw_dir)
    else:
        dir_path = raw_dir
    if not os.path.isdir(dir_path):
        return jsonify({'success': False, 'error': f'目录不存在: {dir_path}'}), 400

    matches = {'ckpt': [], 'pth': [], 'wav': []}
    base_lower = base_name.lower()
    model_dirs = set()
    max_depth = 10

    for root, dirs, files in os.walk(dir_path):
        rel = os.path.relpath(root, dir_path)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirs.clear()
        for f in files:
            ext = os.path.splitext(f)[1].lower().lstrip('.')
            if ext not in ('ckpt', 'pth'):
                continue
            if base_lower in os.path.splitext(f)[0].lower():
                matches[ext].append(os.path.join(root, f))
                model_dirs.add(root)

    ref_texts = []
    # 版本检测：扫描匹配到的 .ckpt 和 .pth 文件头部
    import re
    versions = {'ckpt': None, 'pth': None}
    version_signatures = [
        # 最高优先级：训练路径标记（从训练目录名精确推导）
        (r'logs_s[12]_v2proplas\b', 'V2ProPlas'),
        (r'logs_s[12]_v2pro\b(?!plas)', 'V2Pro'),
        (r'logs_s[12]_v4\b', 'V4'),
        (r'logs_s[12]_v3\b', 'V3'),
        (r'logs_s[12]_v2\b', 'V2'),
        # 高优先级：具体版本标记（文件头/特殊路径）
        ('gsv-v2proplas-pretrained', 'V2ProPlas'),
        ('gsv-v2pro-pretrained', 'V2Pro'),
        ('gsv-v4-pretrained', 'V4'),
        ('gsv-v3-pretrained', 'V3'),
        ('gsv-v2-pretrained', 'V2'),
        ('gsv-v1-pretrained', 'V1'),
        ('weights_v2proplas', 'V2ProPlas'),
        ('weights_v2pro', 'V2Pro'),
        ('SoVITS_weights_v4', 'V4'), ('SoVITS_weights_v3', 'V3'), ('SoVITS_weights_v2', 'V2'),
        ('GPT_weights_v4', 'V4'), ('GPT_weights_v3', 'V3'), ('GPT_weights_v2', 'V2'),
        # 低优先级：通用 version 声明（使用正则防止 v2 匹配 v2proplas 的子串）
        (r'"version"\s*:\s*"v2proplas"', 'V2ProPlas'),
        (r'"version"\s*:\s*"v2pro"', 'V2Pro'),
        (r'"version"\s*:\s*"v4"', 'V4'),
        (r'"version"\s*:\s*"v3"', 'V3'),
        (r'"version"\s*:\s*"v2"', 'V2'),
        (r'"version"\s*:\s*"v1"', 'V1'),
    ]
    for ext_key in ('ckpt', 'pth'):
        if matches[ext_key]:
            try:
                with open(matches[ext_key][0], 'rb') as fh:
                    raw = fh.read(100 * 1024)
                text = raw.decode('utf-8', errors='replace')
                for sig, ver in version_signatures:
                    if re.search(sig, text, re.IGNORECASE):
                        versions[ext_key] = ver
                        break
            except Exception:
                pass
    for md in model_dirs:
        for root, dirs, files in os.walk(md):
            for f in files:
                if f.lower().endswith('.wav'):
                    matches['wav'].append(os.path.join(root, f))
                    txt_path = os.path.join(root, os.path.splitext(f)[0] + '.txt')
                    if os.path.isfile(txt_path):
                        try:
                            # 尝试多种编码读取参考文本
                            try:
                                ref_texts.append(open(txt_path, 'r', encoding='utf-8').read().strip())
                            except UnicodeDecodeError:
                                try:
                                    ref_texts.append(open(txt_path, 'r', encoding='gbk').read().strip())
                                except UnicodeDecodeError:
                                    # 最后尝试系统默认编码
                                    with open(txt_path, 'r', errors='replace') as fh:
                                        ref_texts.append(fh.read().strip())
                        except Exception:
                            ref_texts.append('')
                    else:
                        ref_texts.append('')

    return jsonify({'success': True, 'matches': matches, 'ref_texts': ref_texts, 'versions': versions, 'scanned_dir': dir_path})


@app.route('/files/read', methods=['OPTIONS', 'POST'])
@cross_origin()
def read_file():
    data = request.get_json() or {}
    file_path = data.get('path', '')
    if not file_path or not os.path.isfile(file_path):
        return jsonify({'success': False, 'error': '文件不存在'}), 400
    try:
        with open(file_path, 'rb') as f:
            return send_file(
                io.BytesIO(f.read()),
                mimetype='application/octet-stream',
                as_attachment=True,
                download_name=os.path.basename(file_path),
            )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    print(f"GSV Package API Server v2.0")
    print(f"  搜索路径: {os.path.abspath(BASE_DIR)}")
    print(f"  下载路径: {os.path.abspath(DOWNLOAD_DIR)}")
    print(f"  启动地址: http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=False)
