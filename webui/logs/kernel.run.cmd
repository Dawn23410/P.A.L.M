@echo off
cd /d "D:\P.A.L.M\核心-检验完成\LLM内核"
set "PYTHONUNBUFFERED=1"
set "PYTHONPATH=D:\P.A.L.M\核心-检验完成\LLM内核"
"C:\Users\24459\AppData\Local\Programs\Python\Python310\python.exe" -m palm_llm.server.api --port 10093 > "C:\Users\24459\Desktop\webui\logs\kernel.log" 2> "C:\Users\24459\Desktop\webui\logs\kernel.err.log"
