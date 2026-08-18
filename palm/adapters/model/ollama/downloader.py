"""Ollama 模型下载管理器：国内镜像 / 魔搭社区，支持后台、分片、断点续传与进度。

设计要点：
- 后台：每个下载在独立守护线程中运行，向导关闭也不中断；前端轮询进度。
- 分片：文件按固定大小切分，多个分片用线程池并行 Range 下载，落盘为 .partN。
- 断点续传：已完整下载的分片直接跳过；分片内也按已写字节续传（Range 起点偏移）。
- 进度：采样线程每秒读取磁盘已写字节，计算 speed / eta，供轮询端点返回。
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
import uuid

_LOGGER = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from palm._core.net import request, is_card_present  # 下载统一经网卡门面（默认拒绝外网）

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB / 片
MAX_WORKERS = 4
WORKSPACE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ollama_workspace"
)

# 采样线程调参
SAMPLE_INTERVAL = 0.5    # 采样周期(秒)
EMA_ALPHA = 0.2          # 速度平滑系数：越小越平滑（0~1）
STALL_SPEED = 1024.0     # 低于 1KB/s 视为停滞，ETA 不可信 → None
ETA_MAX = 24 * 3600.0    # ETA 上限 24 小时


class DownloadError(Exception):
    """下载过程中的可预期错误（镜像不可达、校验失败等）。"""


@dataclass
class DownloadJob:
    job_id: str
    model_key: str
    name: str
    source: str
    url: str
    quant_key: str
    dest_path: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed: float = 0.0  # 字节/秒
    eta: Optional[float] = None  # 秒
    status: str = "pending"  # pending|downloading|merging|done|cancelled|failed
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0
    # 运行期瞬态（不入库、不序列化）
    _parts: list = None  # type: ignore
    _is_chunked: bool = False
    lock: "threading.Lock" = field(default_factory=threading.Lock)  # 保护 downloaded_bytes 并发累加
    cancel_event: "threading.Event" = field(default_factory=threading.Event)  # 用户取消信号


class Downloader:
    """进程内单例：管理下载任务与进度。"""

    def __init__(self) -> None:
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()
        os.makedirs(WORKSPACE, exist_ok=True)

    @property
    def workspace(self) -> str:
        return WORKSPACE

    def start(self, model_key: str, name: str, source: str, url: str, filename: str, quant_key: str = "") -> DownloadJob:
        dest = os.path.join(WORKSPACE, filename)
        job = DownloadJob(
            job_id=uuid.uuid4().hex,
            model_key=model_key,
            name=name,
            source=source,
            url=url,
            quant_key=quant_key,
            dest_path=dest,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[DownloadJob]:
        return self._jobs.get(job_id)

    def active_for(self, model_key: str, quant_key: str | None = None) -> Optional[DownloadJob]:
        """返回该模型（及可选精度）仍在进行的任务，用于「后台下载」重入续接。"""
        with self._lock:
            for j in self._jobs.values():
                if j.model_key != model_key:
                    continue
                if quant_key is not None and j.quant_key != quant_key:
                    continue
                if j.status in ("pending", "downloading", "merging"):
                    return j
        return None

    def snapshot(self, job: DownloadJob) -> dict:
        """返回下载快照（含钳制），确保前端 never 看到已下载 > 总量的异常显示。"""
        downloaded = job.downloaded_bytes
        total = job.total_bytes
        if total > 0 and downloaded > total:
            downloaded = total
        return {
            "job_id": job.job_id,
            "model_key": job.model_key,
            "name": job.name,
            "source": job.source,
            "url": job.url,
            "quant_key": job.quant_key,
            "dest_path": job.dest_path,
            "status": job.status,
            "total_bytes": total,
            "downloaded_bytes": downloaded,
            "speed": job.speed,
            "eta": job.eta,
            "error": job.error,
        }

    def cancel(self, job_id: str) -> bool:
        """请求取消正在进行的下载。返回是否成功触发取消。

        仅对 pending/downloading/merging 状态有效；下载线程会在写入下一块时观测到
        cancel_event 并抛出 DownloadCancelled，由 _run 统一置为 cancelled 并清理残留。
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status not in ("pending", "downloading", "merging"):
            return False
        job.cancel_event.set()
        return True

    def _cleanup_partial(self, job: DownloadJob) -> None:
        """取消/失败时清理未完成的残留文件（分片 .partN 与半成品 dest）。"""
        if job._parts:
            for p in job._parts:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError as exc:
                    _LOGGER.debug("分片清理失败 %s: %s", p, exc)
        try:
            if os.path.exists(job.dest_path) and job.status != "done":
                os.remove(job.dest_path)
        except OSError as exc:
            _LOGGER.debug("半成品清理失败 %s: %s", job.dest_path, exc)

    # ---- 内部实现 ----

    def _run(self, job: DownloadJob) -> None:
        job.status = "downloading"
        job.started_at = time.time()
        try:
            if not is_card_present():
                raise DownloadError("网卡未挂载，无法下载模型（需启用网卡砖并经策略授权）")
            total, is_chunked = self._probe(job.url)
            job.total_bytes = total
            job._is_chunked = is_chunked
            stop = threading.Event()
            sampler = threading.Thread(
                target=self._sample_loop, args=(job, stop), daemon=True
            )
            sampler.start()
            try:
                if is_chunked and total:
                    self._download_chunked(job, total)
                else:
                    self._download_sequential(job, total)
            finally:
                # 无论下载正常结束还是被取消，都先停下采样线程。
                stop.set()
                sampler.join()
            if job.cancel_event.is_set():
                # 用户取消：先把状态置为 cancelled（前端轮询立即可见），
                # 残留分片/半成品的清理放到后台守护线程尽力执行，避免 os.remove
                # 在 Windows 上偶因其他线程未释放句柄而阻塞、进而影响状态刷新。
                job.status = "cancelled"
                job.error = "已取消"
                job.finished_at = time.time()
                threading.Thread(target=self._cleanup_partial, args=(job,), daemon=True).start()
                return
            job.status = "merging"
            if job._is_chunked and total:
                self._merge(job, total)
            job.status = "done"
            # 用磁盘真实大小校正总量（probe 探测可能与被下载文件不一致，
            # 例如 CDN 返回的 content-length 与实际文件有偏差）。
            real = os.path.getsize(job.dest_path) if os.path.exists(job.dest_path) else 0
            if real:
                job.total_bytes = real
            job.downloaded_bytes = real or job.total_bytes
            job.finished_at = time.time()
        except Exception as e:  # 任何异常都落到 failed，供前端展示
            job.status = "failed"
            job.error = str(e)
            job.finished_at = time.time()

    def _probe(self, url: str) -> tuple[int, bool]:
        """探测总体积与是否支持分片（Range 206）。"""
        total = 0
        is_chunked = False
        try:
            r = request("HEAD", url, headers={"Accept-Encoding": "identity"},
                        timeout=15.0, follow_redirects=True)
            if r.status_code < 400:
                total = int(r.headers.get("content-length", 0) or 0)
                if "bytes" in (r.headers.get("accept-ranges", "") or ""):
                    is_chunked = True
        except Exception as exc:
            _LOGGER.debug("HEAD 探测失败，降级 GET Range: %s", exc)
        if total == 0 or not is_chunked:
            try:
                r2 = request("GET", url, headers={"Range": "bytes=0-0"},
                             timeout=15.0, follow_redirects=True)
                cr = r2.headers.get("content-range", "")
                if "content-range" in r2.headers and "/" in cr:
                    total = int(cr.split("/")[-1])
                elif "content-length" in r2.headers:
                    total = int(r2.headers["content-length"])
                is_chunked = r2.status_code == 206
            except Exception:
                is_chunked = False
        return total, is_chunked

    def _part_path(self, job: DownloadJob, i: int) -> str:
        return f"{job.dest_path}.part{i}"

    def _chunk_size(self, i: int, total: int) -> int:
        return min(CHUNK_SIZE, total - i * CHUNK_SIZE)

    def _download_chunked(self, job: DownloadJob, total: int) -> None:
        n = math.ceil(total / CHUNK_SIZE)
        parts = [self._part_path(job, i) for i in range(n)]
        job._parts = parts
        missing = [
            i for i in range(n)
            if not (os.path.exists(parts[i]) and os.path.getsize(parts[i]) == self._chunk_size(i, total))
        ]
        if not missing:
            return  # 全部已存在，直接合并
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [
                ex.submit(self._fetch_chunk, job, job.url, i, parts[i], self._chunk_size(i, total))
                for i in missing
            ]
            for fut in futures:
                fut.result()  # 任一分片失败则抛错，任务置 failed
                # 取消信号触发：停掉其余未开始的分片，跳出（已提交的分片会在下一块检查处自行返回）。
                if job.cancel_event.is_set():
                    ex.shutdown(wait=False, cancel_futures=True)
                    break

    def _fetch_chunk(self, job: DownloadJob, url: str, i: int, part: str, size: int) -> None:
        """下载单个分片，支持分片内断点续传。"""
        start = i * CHUNK_SIZE
        end = start + size - 1
        written = os.path.getsize(part) if os.path.exists(part) else 0
        if written >= size:
            return
        req_start = start + written
        headers = {"Range": f"bytes={req_start}-{end}"}
        # 经网卡门面转发（同步流式，chunk_size 由请求透传）；取消检查仍在每块后执行。
        resp = request("GET", url, headers=headers, timeout=300.0,
                       follow_redirects=True, stream=True, chunk_size=256 * 1024)
        if resp.status_code not in (200, 206):
            raise DownloadError(f"分片下载失败：HTTP {resp.status_code}")
        mode = "ab" if written else "wb"
        with open(part, mode) as f:
            if written:
                f.seek(written)
            for block in resp.iter_bytes():
                f.write(block)
                with job.lock:
                    job.downloaded_bytes += len(block)
                if job.cancel_event.is_set():
                    return  # 取消：干净返回，残留 .part 由 _cleanup_partial 清理

    def _download_sequential(self, job: DownloadJob, total: int) -> None:
        """无 Range 支持时的顺序下载（同样支持断点续传）。"""
        if os.path.exists(job.dest_path) and (total == 0 or os.path.getsize(job.dest_path) == total):
            return
        written = os.path.getsize(job.dest_path) if os.path.exists(job.dest_path) else 0
        headers = {"Range": f"bytes={written}-{total - 1 if total else ''}"} if written else {}
        # 经网卡门面转发（同步流式）；取消检查仍在每块后执行。
        resp = request("GET", job.url, headers=headers or None, timeout=600.0,
                       follow_redirects=True, stream=True, chunk_size=256 * 1024)
        if resp.status_code not in (200, 206):
            raise DownloadError(f"下载失败：HTTP {resp.status_code}")
        # 部分 CDN 在 HEAD 不返回 content-length，但 GET 流首部常带；
        # 仅在「全新下载、未续传」时据此补抓总量，使前端进度条可计算百分比。
        # （续传时 206 响应的 content-length 只是剩余分片长度，不能当作总量。）
        if job.total_bytes == 0 and written == 0:
            cl = int(resp.headers.get("content-length", 0) or 0)
            if cl:
                job.total_bytes = cl
        mode = "ab" if written else "wb"
        with open(job.dest_path, mode) as f:
            if written:
                f.seek(written)
            for block in resp.iter_bytes():
                f.write(block)
                with job.lock:
                    job.downloaded_bytes += len(block)
                if job.cancel_event.is_set():
                    return  # 取消：干净返回，残留半成品由 _cleanup_partial 清理

    def _merge(self, job: DownloadJob, total: int) -> None:
        n = math.ceil(total / CHUNK_SIZE)
        with open(job.dest_path, "wb") as out:
            for i in range(n):
                part = self._part_path(job, i)
                with open(part, "rb") as pf:
                    while True:
                        chunk = pf.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                os.remove(part)

    def _on_disk(self, job: DownloadJob) -> int:
        if job._parts:
            return sum(os.path.getsize(p) for p in job._parts if os.path.exists(p))
        return os.path.getsize(job.dest_path) if os.path.exists(job.dest_path) else 0

    def _refresh_speed_eta(
        self, job: DownloadJob, cur: int, prev: Optional[int], elapsed: float
    ) -> Optional[int]:
        """基于采样间隔更新 EWMA 速度与钳制 ETA；返回更新后的 prev 字节数。

        速度过低/停滞时 ETA 置 None，避免荒谬天文数字；总量未知时同样置 None。
        """
        if prev is not None and elapsed > 0:
            instant = (cur - prev) / elapsed
            if instant > 0:
                job.speed = instant if job.speed <= 0 else EMA_ALPHA * instant + (1 - EMA_ALPHA) * job.speed
        if job.total_bytes and cur < job.total_bytes:
            remaining = job.total_bytes - cur
            job.eta = max(0.0, min(remaining / job.speed, ETA_MAX)) if job.speed >= STALL_SPEED else None
        elif job.total_bytes and cur >= job.total_bytes:
            job.eta = 0.0
        else:
            job.eta = None
        return cur

    def _sample_loop(self, job: DownloadJob, stop: threading.Event) -> None:
        """周期性估算速度与 ETA。

        进度(downloaded_bytes)的**权威实时来源是下载线程本身**（分片/顺序下载每写一块就
        累加，见 _fetch_chunk / _download_sequential），本采样线程只做：
        1) 以磁盘实际大小做交叉校验，取「实时计数 / 磁盘大小」的较大者，避免缓冲或时序
           造成的回退（绝不把进度清零）；
        2) 基于交叉后的 cur 计算 EWMA 平滑速度与 ETA。
        这样即便采样线程因 GIL 被短暂饿死，前端轮询读到的 downloaded_bytes 也始终是真实进度。
        """
        prev: Optional[int] = None   # 上一次采样字节数；None=冷启动首拍
        t0 = time.time()
        while not stop.is_set():
            # 实时计数（下载线程累加）与磁盘大小交叉校验，取较大者作为可信进度。
            total = job.total_bytes
            with job.lock:
                live = job.downloaded_bytes
            disk = self._on_disk(job)
            cur = disk if disk > live else live
            if total and cur > total:
                cur = total  # 钳制到已知总量，避免任何来源导致的过冲
            with job.lock:
                # 向下钳制：若实时计数已超过总量，拉回总量（修复因服务器返回超出
                # 分片范围的数据导致 downloaded_bytes 永久超过 total 的仪表显示 bug）。
                if total and job.downloaded_bytes > total:
                    job.downloaded_bytes = total
                if cur > job.downloaded_bytes:
                    job.downloaded_bytes = cur
            now = time.time()
            elapsed = now - t0
            if elapsed >= SAMPLE_INTERVAL:
                prev = self._refresh_speed_eta(job, cur, prev, elapsed)
                t0 = now
            if job.total_bytes and cur >= job.total_bytes:
                break
            time.sleep(SAMPLE_INTERVAL)


manager = Downloader()
