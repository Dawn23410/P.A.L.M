import json, time, urllib.request, statistics as st

REF = r'C:/Users/24459/Desktop/v4/芙宁娜_ZH/reference_audios/中文/emotions/【默认】根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？.wav'
PT  = '根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？'
BASE = 'http://127.0.0.1:10080'

def ttfb(text, streaming=True):
    body = json.dumps({'text':text,'text_lang':'zh','ref_audio_path':REF,'prompt_text':PT,
        'prompt_lang':'zh','text_split_method':'cut5','media_type':'wav','streaming_mode':streaming,
        'sample_steps':16}).encode('utf-8')
    req = urllib.request.Request(BASE+'/tts', data=body, headers={'Content-Type':'application/json'})
    t0=time.perf_counter(); first=None; n=0
    with urllib.request.urlopen(req, timeout=180) as r:
        while True:
            c=r.read(65536)
            if not c: break
            if first is None: first=time.perf_counter()-t0
            n+=len(c)
    return first, time.perf_counter()-t0, n

def dist_report(name, samples):
    s = sorted(samples)
    n=len(s)
    def pct(p):
        idx=min(n-1, int(p*n))
        return s[idx]
    print(f"[{name}] n={n}  min={s[0]:.3f}  p50={pct(0.5):.3f}  p90={pct(0.9):.3f}  p95={pct(0.95):.3f}  max={s[-1]:.3f}  mean={st.mean(s):.3f}  std={st.pstdev(s):.3f}")

# 预热 3 次（吞掉 CUDA 首次内核编译 / 模型热身）
for i in range(3):
    ttfb('预热一下。')
print("== 预热完成，开始采样 ==")
print()

SHORT = '好的，我马上帮你处理这个问题。'
LONG  = ('好的呀，我现在就帮你处理这个问题。首先我们需要确认一下参数设置，'
         '然后再进行下一步操作。如果中间遇到什么报错，我会及时告诉你的。'
         '整个过程大概需要几分钟，请耐心等待一下哦。')

# 同短文本重复 20 次 → 隔离 TTFB 方差（不含文本长度影响）
short_ttfb=[]
for i in range(20):
    f,_,_ = ttfb(SHORT)
    short_ttfb.append(f)
    print(f"  短句{i+1:02d}: TTFB={f:.3f}s")
print()
dist_report("同短文本×20 TTFB", short_ttfb)
print()

# 不同长度 12 次
mixed_ttfb=[]; mixed_total=[]
for i in range(12):
    t = SHORT if i%2==0 else LONG
    f,tot,_ = ttfb(t)
    mixed_ttfb.append(f); mixed_total.append(tot)
    print(f"  混合{i+1:02d} ({'短' if i%2==0 else '长'}): TTFB={f:.3f}s total={tot:.3f}s")
print()
dist_report("混合长度×12 TTFB", mixed_ttfb)
dist_report("混合长度×12 总耗时", mixed_total)
