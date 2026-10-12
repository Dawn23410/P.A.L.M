import json, time, urllib.request

REF = r'C:/Users/24459/Desktop/v4/芙宁娜_ZH/reference_audios/中文/emotions/【默认】根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？.wav'
PT  = '根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？'
BASE = 'http://127.0.0.1:10080'
TXT  = '好的，我马上帮你处理这个问题。'

def ttfb(idle):
    if idle>0: time.sleep(idle)
    body = json.dumps({'text':TXT,'text_lang':'zh','ref_audio_path':REF,'prompt_text':PT,
        'prompt_lang':'zh','text_split_method':'cut5','media_type':'wav','streaming_mode':True,
        'sample_steps':16}).encode('utf-8')
    req = urllib.request.Request(BASE+'/tts', data=body, headers={'Content-Type':'application/json'})
    t0=time.perf_counter(); first=None
    with urllib.request.urlopen(req, timeout=180) as r:
        while True:
            c=r.read(65536)
            if not c: break
            if first is None: first=time.perf_counter()-t0
    return first

print("== 不同空闲间隔后的 TTFB（捕捉 GPU 降频回升）==")
for idle in (0, 2, 5, 10, 15, 30, 45):
    f = ttfb(idle)
    print(f"  空闲{idle:2d}s 后 TTFB = {f:.3f}s")
