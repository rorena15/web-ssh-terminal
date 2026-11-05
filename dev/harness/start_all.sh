#!/bin/sh
# 시험용 가짜 서버 + W.S.T 서버(TLS 없이 18022) 기동. 실행 결과물은 dev/harness/run/ 에 쌓인다(지워도 됨).
H="$(cd "$(dirname "$0")" && pwd)"
R="$H/run"
mkdir -p "$R/sftproot/home/test" "$R/ftproot/pub" "$R/data"
[ -f "$R/sftproot/home/test/a.txt" ] || printf 'hello\n' > "$R/sftproot/home/test/a.txt"
python "$H/fake_rlogin.py" 2513 > "$R/rlogin.log" 2>&1 &
cd "$H/../.."
python "$H/fake_sshd.py" 2222 "$R/sftproot" > "$R/sshd.log" 2>&1 &
python "$H/fake_telnet.py" 2323 > "$R/telnet.log" 2>&1 &
PYTHONIOENCODING=utf-8 WEBSSH_DATA="$R/data" python server.py --no-token --no-tls --port 18022 > "$R/web.log" 2>&1 &
wait
