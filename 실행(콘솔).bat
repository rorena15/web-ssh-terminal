@echo off
rem 설치·문제 확인용: 콘솔 창에 서버 로그가 보입니다. 평소에는 실행.vbs (창 없이 실행)
chcp 65001 >nul
cd /d "%~dp0"
rem websockets 17.4 미만은 메모리 고갈 취약점(GHSA-6m5v-9gmr-5665) → 업그레이드
python -c "import paramiko, cryptography, winpty, websockets, sys; sys.exit(tuple(int(x) for x in websockets.__version__.split('.')[:2]) < (17, 4))" 2>nul || python -m pip install -q -U paramiko "websockets>=17.4" cryptography pywinpty
python server.py --open --trust %*
pause
