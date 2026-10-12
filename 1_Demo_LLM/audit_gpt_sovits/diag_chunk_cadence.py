import json, time, urllib.request

REF = r'C:/Users/24459/Desktop/v4/芙宁娜_ZH/reference_audios/中文/emotions/【默认】根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？.wav'
PT  = '根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？'
BASE = 'http://127.0.0.1:10080'
LONG = ('好的呀，我现在就帮你处理这个问题。首先我们需要确认一下参数设置，'
        '然后再进行下一步操作。如果中间遇到什么报错，我会及时告诉你的。'
        '整个过程大概需要几分钟，请耐心等待一下哦。')

def chunk_times():
    body = json.dumps({'text':LONG,'text_lang':'zh','ref_audio_path':REF,'prompt_text':PT,
        'prompt_lang':'zh','text_split_method':'cut5','media_type':'wav','streaming_mode':True,
        'sample_steps':16}).encode('utf-8')
    req = urllib.request.Request(BASE+'/tts', data=body, headers={'Content-Type':'application/json'})
    t0=time.perf_counter(); marks=[]; first=None
    with urllib.request.urlopen(req, timeout=180) as r:
        while True:
            c=r.read(65536)
            if not c: break
            now=time.perf_counter()-t0
            if first is None: first=now
            marks.append((now, len(c)))
    return first, marks

print("== 长文本流式分块到达时间戳 ==")
first, marks = chunk_times()
print(f"首块 TTFB={first:.3f}s, 共 {len(marks)} 块, 总时长 {marks[-1][0]:.3f}s")
# 块间间隔
gaps=[]
for i in range(1,len(marks)):
    g = marks[i][0]-marks[i-1][0]
    gaps.append(g)
import statistics as st
print(f"块间间隔: min={min(gaps):.3f} p50={sorted(gaps)[len(gaps)//2]:.3f} max={max(gaps):.3f} mean={st.mean(gaps):.3f} std={st.pstdev(gaps):.3f}")
# 打印前 12 块与最后 5 块
for i,(t,sz) in enumerate(marks[:12]):
    print(f"  块{i:02d} t={t:.3f}s +{sz}B")
print("  ...")
for i,(t,sz) in enumerate(marks[-5:], start=len(marks)-5):
    print(f"  块{i:02d} t={t:.3f}s +{sz}B")
# 找最大间隔位置
mx=max(gaps); mi=gaps.index(mx)
print(f"\n最大间隔 {mx:.3f}s 出现在 块{mi}→块{mi+1} 之间")
