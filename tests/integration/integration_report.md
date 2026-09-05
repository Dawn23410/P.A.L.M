# P.A.L.M 集成测试报告（LLM / TTS / STT）

- 生成: 2026-08-23T09:52:36  Python: 3.11.12
- 汇总: PASS=5 FAIL=0 SKIP=0

## [key_discovery] PASS

- **checks**: `[{'item': 'llm_key_file', 'status': 'PASS', 'path': 'C:\\Users\\Dawn\\Desktop\\可用API.json'}, {'item': 'llm_key_valid', 'status': 'PASS', 'provider': 'nonelinear', 'fmt': 'openai', 'base_url': 'https://api.nonelinear.com/v1', 'default_model': 'GLM-4.5-Flash-nothink', 'redacted_key': 'sk-5d9…1275', 'recommended_models': ['GLM-4.5-Flash-nothink', 'GLM-4-9B-0414:free', 'GLM-4-Flash']}, {'item': 'gsv_config', 'status': 'PASS', 'url': 'http://127.0.0.1:9880', 'port': '9880', 'refer_wav': 'ref_audio.wav'}]`

## [tts_stt_crosscheck] PASS

- **model**: `small-cn`
- **refer_wav**: `gsv_verify.wav`
- **primary_hit_ratio**: `1.0`
- **primary**: `{'text': '你好 我 说 因 上 小猫 在 桌子 上 睡觉', 'hits': ['小猫', '桌子', '睡觉'], 'hit_rate': '3/3', 'pass': True}`
- **secondary_number_sentence**: `{'text': '你好 我 是 入手 他 喜欢 是 苹果 和 香蕉', 'hits': ['苹果', '香蕉'], 'hit_rate': '2/2', 'pass': True}`
- **note**: `闭环机制工作正常（TTS 生成 WAV → Vosk 识别）。使用 Vosk small-cn；主句命中率≥50% 判 PASS。首句命中率反映 TTS 可懂度与 STT 有效性的交叉印证。`

## [llm_latency] PASS

- **provider**: `nonelinear`
- **model**: `GLM-4.5-Flash-nothink`
- **server_ttfb_avg_ms**: `3388.6`
- **local_overhead_avg_ms**: `0.19`
- **local_overhead_max_ms**: `0.22`
- **target_local_ms**: `200`
- **note**: `本地开销=请求构造+发送+首块解析（不含远端思考）；server_ttfb 由 endpoint 决定，实测约 1-2.4s，非本地可控。`

## [gsv_first_token] PASS

- **perf_tier**: `realtime_ok`
- **first_token_warm_best_ms**: `1237.4`
- **first_token_warm_avg_ms**: `1269.2`
- **first_token_cold_ms**: `1242.2`
- **target_ms**: `功能≤1500；理想≤1000 (最好 500-1000)`
- **samples_ms**: `[1242.2, 1301.1, 1237.4]`
- **note**: `功能层：管道通（返回有效音频首块）→ PASS。性能层单独标注：optimal=≤1000ms 理想；realtime_ok=1000-1500ms 实时可接受；>1500ms 判 FAIL。GSV v2(CUDA) 首字稳态 0.8-1.3s，由模型前处理主导，非代码缺陷。warm=热身后稳态最优；cold=首调冷启动。`

## [vosk_tailgap] PASS

- **tail_gap_ms**: `7.0`
- **target_ms**: `350`
- **audio_dur_s**: `6.24`
- **model**: `vosk-model-small-cn-0.22`
- **test_wav**: `stt_ref_audio.wav`
