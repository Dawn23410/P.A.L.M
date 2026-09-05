#!/bin/bash
set -e
docker run -d --name palm_voice_gpu \
  --add-host host.docker.internal:172.23.48.1 \
  -e RUN_VOICE=1 \
  -e MENTALCORE_API_KEY=[REDACTED_API_KEY] \
  -e MENTALCORE_MODEL=GLM-4.5-Flash-nothink \
  -e MENTALCORE_MODE=live \
  -e MENTALCORE_PROVIDER_MODE=openai \
  -e MENTALCORE_BASE_URL=https://api.nonelinear.com/v1 \
  -e PALM_OFFLINE=0 \
  -e PALM_DATA=/data \
  -e PALM_API_JSON=/data/可用API.json \
  -v /opt/vosk-model-small-cn-0.22:/opt/vosk-model-small-cn-0.22 \
  -v /root/projects/P.A.L.M/mentalcore:/opt/palm/mentalcore \
  palm:test \
  bash -c "pip install soundfile -q 2>/dev/null; cd /opt/palm/mentalcore; python run50_voice.py --rounds 5 --voice-rounds 5 --vosk-model /opt/vosk-model-small-cn-0.22 --refer-wav 'C:/Users/Dawn/Desktop/P.A.L.M/refer_audio_tmp.wav' --refer-text '今天 天气 真好 我们 去 公园 散步 吧'"
echo "STARTED palm_voice_gpu"
docker ps -a --filter name=palm_voice_gpu --format "table {{.Names}}\t{{.Status}}"
