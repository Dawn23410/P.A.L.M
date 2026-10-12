import json, time, urllib.request
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

# 热身
tts('预热。')
print("=== 端到端最终验证（发原始文本，验证服务端预处理已自动纠正）===")
f,t,n = tts('请等待30-60s后重试。', out='final_30-60s.wav')
print(f"[30-60s]      TTFB={f:.2f}s total={t:.2f}s -> 应读「三十到六十秒」")
f,t,n = tts('如需帮助请拨打138-0013-8000联系客服。', out='final_phone.wav')
print(f"[电话]        TTFB={f:.2f}s total={t:.2f}s -> 应读「幺三八零零幺三八零零零」(无减)")
f,t,n = tts('文件生成于2024-09-27，版本v2到v3。', out='final_date.wav')
print(f"[日期+版本]   TTFB={f:.2f}s total={t:.2f}s -> 日期保留/版本不崩")
f,t,n = tts('好的呀，我现在就帮你处理这个问题。请稍等。', out='final_short2.wav')
print(f"[短句]        TTFB={f:.2f}s total={t:.2f}s")
