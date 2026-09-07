# -*- coding: utf-8 -*-
"""性能占用实测 v1.0：内存（RSS 分阶段）/ 首载分解 / 稳态延迟分布 / CPU 时间
独立进程跑（psutil 自测当前进程），产出 json + stdout。
"""
import sys, io, json, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")

import psutil
proc = psutil.Process()
OUT = {}

def rss_mb():
    return proc.memory_info().rss / 1024 / 1024

OUT["python_base_rss_mb"] = round(rss_mb(), 1)

t0 = time.perf_counter()
from local_reply.engine.engine import StitchEngine
OUT["import_s"] = round(time.perf_counter() - t0, 3)
OUT["after_import_rss_mb"] = round(rss_mb(), 1)

t0 = time.perf_counter()
eng = StitchEngine(semantic=True)
OUT["boot_total_s"] = round(time.perf_counter() - t0, 3)
OUT["after_boot_rss_mb"] = round(rss_mb(), 1)

# 首次 embed（含 session 真正实例化）
t0 = time.perf_counter()
eng.respond("你好")
OUT["first_respond_s"] = round(time.perf_counter() - t0, 3)
OUT["after_warm_rss_mb"] = round(rss_mb(), 1)

# 稳态延迟分布：60 句混合（寒暄/情绪/日常/长句），每句 2 抽 = 120 样本
QUERIES = [
    "你好", "在吗", "吃了吗", "晚安", "早安", "我好累", "好烦啊", "不开心",
    "想你了", "抱抱我", "被领导骂了", "房租又涨了", "快递丢件了", "面试完感觉凉了",
    "养的猫生病了", "跟室友吵了一架", "感冒了鼻子堵得慌", "连续加班一周了",
    "今天穿什么", "晚饭吃什么", "周末有啥安排", "推荐个下饭剧呗",
    "今天开了一下午会，脑子嗡嗡的，想听你说说话",
    "刚跟家里通完电话，被催婚了，烦", "外面下雨了，突然有点想你",
    "最近总失眠，白天又困，恶性循环了", "考试挂了", "涨工资了", "下冰雹了",
    "回南天墙壁冒水",
]
lat, cpu = [], []
for q in QUERIES:
    for _ in range(2):
        c0 = time.process_time()
        t0 = time.perf_counter()
        eng.respond(q)
        lat.append((time.perf_counter() - t0) * 1000)
        cpu.append((time.process_time() - c0) * 1000)
lat.sort(); cpu.sort()
n = len(lat)
OUT["steady_latency_ms"] = {
    "n": n, "min": round(lat[0], 1), "median": round(lat[n // 2], 1),
    "p90": round(lat[int(n * 0.9)], 1), "p99": round(lat[int(n * 0.99)], 1),
    "max": round(lat[-1], 1),
}
OUT["steady_cpu_ms"] = {
    "median": round(cpu[n // 2], 1), "p99": round(cpu[int(n * 0.99)], 1),
}
OUT["peak_rss_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
# 子线程数（onnxruntime 线程池）
OUT["threads"] = proc.num_threads()
# 系统总内存上下文
vm = psutil.virtual_memory()
OUT["system_total_mem_gb"] = round(vm.total / 1024**3, 1)
OUT["engine_share_of_ram_pct"] = round(OUT["peak_rss_mb"] / (vm.total / 1024**2) * 100, 1)

with open(r"C:\Users\Dawn\Desktop\local_reply_engine\perf_profile_v1.0.json", "w", encoding="utf-8") as fh:
    json.dump(OUT, fh, ensure_ascii=False, indent=2)
print(json.dumps(OUT, ensure_ascii=False, indent=2))
