# 声纹识别砖准确性验证报告

- 模型：CAM++ fp16 ONNX（campplus_zh_en_fp16.onnx，192 维，中文训练）
- 检验集来源：**CosyVoice 砖零样本克隆生成**（非真实人声，见下方说明）
- 检验集规模：12 条 / 3 说话人（spkA, spkB, spkC），每说话人 4 句不同文案
- 注册：每说话人第 1 句；测试：其余 9 句做 1:N 识别

## 结论

| 指标 | 数值 |
|---|---|
| 1:N 识别准确率 @0.31 | **100.0%** (9/9) |
| EER（等错误率） | **0.0%** @ 阈值 0.450 |
| 同说话人相似度均值（genuine） | 0.905 |
| 跨说话人最高相似度均值（impostor） | 0.361 |
| 分离度（genuine - impostor） | 0.544 |

## 逐句识别结果

| 文件 | 真实说话人 | 识别结果 | 相似度 | 正确 |
|---|---|---|---|---|
| spkA_2.wav | spkA | spkA | 0.909 | ✓ |
| spkA_3.wav | spkA | spkA | 0.776 | ✓ |
| spkA_4.wav | spkA | spkA | 0.890 | ✓ |
| spkB_2.wav | spkB | spkB | 0.942 | ✓ |
| spkB_3.wav | spkB | spkB | 0.960 | ✓ |
| spkB_4.wav | spkB | spkB | 0.965 | ✓ |
| spkC_2.wav | spkC | spkC | 0.887 | ✓ |
| spkC_3.wav | spkC | spkC | 0.927 | ✓ |
| spkC_4.wav | spkC | spkC | 0.893 | ✓ |

## 说明与局限

1. **检验集是 TTS 合成语音**，非真实人声。CAM++ 在真实语音上训练，对合成语音的
   嵌入空间可能偏移；因此上述准确率/EER 衡量的是「同一克隆音色跨文本的稳定性」与
   「不同克隆音色间的区分度」，作为砖功能可用性的冒烟级验证，**不替代真实人声基准**。
2. 真实人声基准建议用 CN-Celeb / VoxCeleb 子集或实际麦克风录音复测，预期 EER 更低
   （CAM++ 在 CN-Celeb 报告 EER≈4.3%）。
3. 阈值 0.450 由本检验集扫描得到；上线前应以真实人声重新标定 SPEAKER_THRESHOLD。

## 复现

```bash
# 1. 生成检验集（需 CosyVoice 砖 venv）
语音合成 (CosyVoice)/.venv/Scripts/python.exe 声纹识别/test_data/gen_test_set.py
# 2. 跑准确性验证（声纹砖 venv）
声纹识别/.venv-speaker/Scripts/python.exe 声纹识别/accuracy_test.py
```
