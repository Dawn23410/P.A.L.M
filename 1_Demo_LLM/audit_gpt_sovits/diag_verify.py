import json, time, urllib.request, os
REF = r'C:/Users/24459/Desktop/v4/芙宁娜_ZH/reference_audios/中文/emotions/【默认】根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？.wav'
PT  = '根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？'
BASE = 'http://127.0.0.1:10080'

def tts(text, out=None, streaming=True):
    body = json.dumps({'text':text,'text_lang':'zh','ref_audio_path':REF,'prompt_text':PT,
        'prompt_lang':'zh','text_split_method':'cut5','media_type':'wav','streaming_mode':streaming,
        'sample_steps':16}).encode('utf-8')
    req = urllib.request.Request(BASE+'/tts', data=body, headers={'Content-Type':'application/json'})
    t0=time.perf_counter(); first=None; buf=bytearray()
    with urllib.request.urlopen(req, timeout=180) as r:
        while True:
            c=r.read(65536)
            if not c: break
            if first is None: first=time.perf_counter()-t0
            buf.extend(c)
    if out: open(out,'wb').write(bytes(buf))
    return first, time.perf_counter()-t0, len(buf)

# 1) 热态首字延迟（流式，目标<2s）
f,t,n = tts('请稍等。')  # 热身
f,t,n = tts('好的，我马上帮你处理这个问题。', out='v_short.wav')
print(f'[热态] 短句首字 TTFB={f:.2f}s  total={t:.2f}s  {n//1024}KB')
print()

# 2) 数字/单位归一：坏(原始) vs 好(预处理后) 对照样片
raw = '请等待30-60s后重试。'
fixed = '请等待三十到六十秒后重试。'
f1,t1,_ = tts(raw, out='v_bad_30-60s.wav')
f2,t2,_ = tts(fixed, out='v_good_30-60s.wav')
print(f'[坏] 原始 "{raw}"  -> TTFB={f1:.2f}s (听感应为: 三十减六十 ess)')
print(f'[好] 预处理 "{fixed}" -> TTFB={f2:.2f}s (听感应是: 三十到六十秒)')
