"""parse 砖块控制器：类型识别 + 分发 + 合并结构化输出。

路由规则：
- 图片（png/jpg/...）            -> 预处理 -> OCR（img_ocr）
- 文档（docx/pptx/xlsx/pdf/...） -> doc2struct；其中挑出的图片 -> 预处理 -> OCR，文本并入结果
- 文本（html/txt/csv/md/json）   -> doc2struct

工具脚本以库方式调用（to_structured），重型依赖懒加载，不在导入期触发。
OCR 引擎单例 + 单线程 executor 串行处理，避免并发推理竞争。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from palm._core.paths import brick_local

from .jobs import Job, store
from .types import EXCEPTION_CODES, is_supported, kind_of

TOOLS_DIR = Path(brick_local(__file__, "tools"))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

WORKSPACE = Path(brick_local(__file__, "parse_workspace"))

_ocr_engine = None
_engine_lock = threading.Lock()


def is_ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine in (None, "UNAVAILABLE"):
        with _engine_lock:
            if _ocr_engine in (None, "UNAVAILABLE"):
                try:
                    import img_ocr
                    _ocr_engine = img_ocr.build_ocr_engine(True)
                except SystemExit:
                    _ocr_engine = "UNAVAILABLE"
    return None if _ocr_engine == "UNAVAILABLE" else _ocr_engine


def _fail(job: Job, code: str, message: str) -> None:
    store.update(job, status="failed", code=code,
                code_num=EXCEPTION_CODES.get(code), message=message)


def _fail_unsupported(job: Job, filename: str) -> None:
    ext = Path(filename).suffix
    _fail(job, "UNSUPPORTED_FILE", f"不支持的文件类型：{ext or '无扩展名'}")


def _ocr_on_image(ip: Path, engine) -> dict | None:
    import img_ocr
    import img_preprocess

    proc_path = ip.with_name(ip.stem + ".proc.png")
    target = ip
    try:
        img_preprocess.process_image(
            str(ip), max_size=1280, moire_sigma=1.0,
            binarize=False, threshold="otsu", sharpen=True, save_path=str(proc_path),
        )
        if proc_path.exists():
            target = proc_path
    except Exception:
        target = ip
    try:
        return img_ocr.to_structured(target, engine, img_ocr.DEFAULT_MIN_CONFIDENCE)
    except Exception:
        return None


def _ocr_images(doc: dict, images: list[dict]) -> None:
    engine = _get_ocr_engine()
    if engine is None:
        doc.setdefault("metadata", {})["ocr"] = "skipped: engine unavailable"
        return
    extra: list[str] = []
    for im in images:
        ocr_output = _ocr_on_image(Path(im["path"]), engine)
        if not ocr_output or not ocr_output["content"]:
            continue
        im["ocr"] = {
            "text": ocr_output["content"],
            "avg_confidence": ocr_output["metadata"]["avg_confidence"],
            "block_count": ocr_output["metadata"]["block_count"],
        }
        doc["structure"].append({
            "type": "ocr_image", "name": im["name"],
            "text": ocr_output["content"], "confidence": ocr_output["metadata"]["avg_confidence"],
        })
        extra.append(f"[图片 {im['name']} 文字]\n{ocr_output['content']}")
    if extra:
        add = "\n\n".join(extra)
        doc["content"] = (doc["content"] + "\n\n" + add).strip() if doc["content"] else add
        doc.setdefault("metadata", {})["ocr_image_count"] = len(extra)


def _ocr_image(src: Path, job_dir: Path) -> dict:
    if not is_ocr_available():
        raise RuntimeError("ENGINE_UNAVAILABLE")
    engine = _get_ocr_engine()
    if engine is None:
        raise RuntimeError("ENGINE_UNAVAILABLE")
    import img_ocr
    doc = img_ocr.to_structured(src, engine, img_ocr.DEFAULT_MIN_CONFIDENCE)
    doc["kind"] = "image_ocr"
    return doc


def _parse_document_structure(src: Path, job_dir: Path) -> dict:
    import doc2struct
    images_dir = job_dir / f"{src.stem}_images"
    doc = doc2struct.to_structured(src, max_chars=0, images_dir=images_dir)
    doc["kind"] = "document"
    images = doc.get("images")
    if images:
        _ocr_images(doc, images)
    return doc


def _parse_text(src: Path, job_dir: Path) -> dict:
    """轻量文本解析：纯文本类（txt/md/json/csv/html）直接读内容成结构化，
    不依赖 doc2struct，使其在无重型依赖时也能离线跑通。"""
    text = src.read_text(encoding="utf-8", errors="replace")
    return {
        "kind": "text",
        "content": text,
        "structure": [{"type": "text", "name": src.name, "text": text}],
    }


def run_parse_job(job: Job, file_bytes: bytes, filename: str) -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    job_dir = WORKSPACE / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    src = job_dir / filename
    src.write_bytes(file_bytes)
    store.update(job, status="processing", progress=10)

    if not is_supported(src):
        _fail_unsupported(job, filename)
        return
    try:
        kind = kind_of(src)
        if kind == "image":
            parsed_image = _ocr_image(src, job_dir)
            parsed_image["job_id"] = job.job_id
            store.update(job, status="done", progress=100, result=parsed_image)
        elif kind == "text":
            parsed_doc = _parse_text(src, job_dir)
            parsed_doc["job_id"] = job.job_id
            store.update(job, status="done", progress=100, result=parsed_doc)
        else:
            parsed_doc = _parse_document_structure(src, job_dir)
            parsed_doc["job_id"] = job.job_id
            store.update(job, status="done", progress=100, result=parsed_doc)
    except Exception as exc:  # noqa: BLE001
        # OCR 引擎不可用（缺 rapidocr/opencv/numpy 依赖）应映射到 ENGINE_UNAVAILABLE(5002)，
        # 而非被通用分支误归为 PROCESS_FAILED(5001)，便于前端区分「引擎未装」与「处理异常」。
        if str(exc) == "ENGINE_UNAVAILABLE":
            _fail(job, "ENGINE_UNAVAILABLE", "OCR 引擎不可用（缺少 rapidocr/opencv/numpy 依赖）")
        else:
            _fail(job, "PROCESS_FAILED", f"{type(exc).__name__}: {exc}")
