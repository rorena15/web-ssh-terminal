# 개발용 시험 도구

실제 서버 없이 앱 전체를 시험하는 도구. 배포(exe)에는 들어가지 않는다.

| 파일 | 역할 |
|---|---|
| `harness/fake_sshd.py <포트> <루트>` | 가짜 SSH 서버(셸·exec·SFTP·direct-tcpip·원격 포워딩·X11 클라이언트 흉내 `xclient good\|bad\|none`). 비밀번호 `pw`. `--demo`는 README용 명령 출력·모니터링 값 제공(기본 꺼짐) |
| `harness/fake_telnet.py <포트>`, `fake_ftpd.py`, `fake_vnc.py` | 가짜 Telnet·FTP·VNC 서버 |
| `harness/start_all.sh` | 가짜 SSH(2222)·Telnet(2323) + W.S.T 서버(`--no-token --no-tls --port 18022`, 데이터는 `harness/run/data`) 기동 |
| `harness/cdp.py <URL> <스크립트.js 또는 ->` | 크롬을 원격 디버깅으로 띄워 페이지에서 JS 실행, 결과 JSON 출력 |
| `harness/lib.js` | 시험 공통 함수(대기, 호스트 키·비밀번호 창 자동 응답, 빠른 접속) |
| `harness/t_smoke.js`, `t_1a.js`, `s1.js`, `s2.js` | 시나리오 시험 (`t_smoke`·`t_1a`는 lib.js를 이미 포함 → 파일로 바로 넘김) |
| `harness/t_3.js`, `t_9.js`, `t_15.js` | 3단계 / Telnet 게이트웨이 첫 호스트 키 / 틀린 키 암호 재질문 (lib.js 앞에 붙임. `t_9`는 빈 데이터 폴더로, `t_15`는 앞에 `const KEY='키 경로';`) |
| `harness/t_fix_1104.py <키 폴더>` | 파이썬 시험: 게이트웨이 RDP 주소·자격 증명 분리, 틀린 키 암호, 터널 중지 경쟁 (가짜 sshd 2222 필요, 키는 `ssh-keygen -N right`) |
| `harness/t_d1_x11.py`, `t_d234.py`, `t_d5.js` | 11/4 결함 D1~D5 시험 — agy가 명세(`docs/SPEC_D1-D5_2026-11-04.md`)만 보고 작성. D1은 6000번이 비어 있어야 함(쓰이면 종료 코드 2), `t_d5.js`는 앞에 `const KEY=…;` + lib.js |
| `harness/t_e18.py` | 11/4 결함 E1~E5·E8a 시험 — agy가 `docs/SPEC_E1-E8_2026-11-04.md`만 보고 작성 (가짜 sshd 2222 필요) |
| `harness/t_gui_e1.js` | GUI E안 1단계 배치·디자인 시험 — agy가 `docs/SPEC_GUI_E1_2026-11-04.md`만 보고 작성. lib.js 앞에 붙임 |
| `harness/t_font.js`, `t_uifont.js`, `t_uiscale.js`, `t_help.js`, `t_sftp_failure.js` | 11/4 터미널·화면 글자, 도움말·버전·라이선스·설정 창, SFTP 불가 화면 시험 (lib.js 앞에 붙임. `t_sftp_failure`는 `fake_sshd.py 2223 <루트> --deny-file-access` 필요) |
| `harness/t_x11.py` | X11 쿠키 검증·교체 (가짜 sshd 2222 + 6000번 가짜 X 서버, 실제 X 서버가 6000에 떠 있으면 안 됨) |
| `harness/t_b1.py` | 11/13 명세 B1(원격 모드·로컬 CA 제거, Host 검사, 이전 CA 정리, websockets 버전 거부, 파일 서버 기본 127.0.0.1, 다운로드 티켓 1회용) 시험 — agy가 `docs/SPEC_B1_2026-11-13.md`만 보고 작성, S5 가짜 세션 구조는 Claude 수정. 서버를 직접 띄움(빈 포트) |
| `harness/t_dlout.js` | 11/13 SFTP 끌어 내려받기(Claude 검증): 행 pointerdown→dragstart의 DownloadURL로 받기, 같은 행 재끌기 200·쓴 링크 404·5개 동시 200. lib.js 앞에 붙임, 가짜 sshd 2222 루트의 `/home/test/f1.bin~f5.bin`(각 8MB) 필요 |
| `harness/t_dlclose.py [저장소 루트]` | 11/13 끌어 내려받기 채널 캐시·세션 종료 정리(Claude 검증): 채널 재사용·직렬화, 죽은 채널 재시도, `close_dl`(진행 중 내려받기 뒤 닫기, 그 세션 링크 삭제, 이후 None). 서버·sshd 불필요 |
| `harness/t_update.py [저장소 루트]` | 11/13 자동 업데이트 명세 시험 — agy가 `docs/SPEC_UPDATE_2026-11-13.md`만 보고 작성(https 처리기 우선순위·버전 파일 위치·plan 기대값은 Claude 수정). 서명·변조·다운그레이드·경로 규칙·Range/전체 받기·적용/복구·잠금·설정. 시험 키·로컬 HTTP 서버 사용, 인터넷 접속 없음 |
| `harness/t_update_lock.py [저장소 루트]` | 11/13 업데이트 잠금(Claude 검증): 죽은·살아 있는 pid, 깨진 형식, 시작 정리, 인수 잠금 누수, launch_ready 예외 안전 |
| `release/make_zip.py`, `make_manifest.py`, `sign_manifest.py`, `make_update_key.py` | 릴리즈 zip·manifest 생성, 서명(CI에서 `WST_UPDATE_KEY`), 업데이트 키 생성. CI `.github/workflows/release.yml`이 사용 |
| `harness/t_rdp_launch.py` | 11/13 RDP 실행 방식 시험(Claude 검증): 기본 `mstsc /v:` 인수·옵션, 클립보드 끔·드라이브 연결만 .rdp 파일, 주소·문자열 주입 거부, 실제 mstsc에서 RDP 파일 보안 경고 없음(대상 127.0.0.1:1). `--no-real`이면 mstsc 미실행 |
| `harness/t_sec2.py`, `t_sec2.js`, `t_sec2_front.py` | 11/5 보안 2차(T1 토큰·T2 프록시·T3 RDP·T4 바로가기·T5 option) 시험 — agy가 `docs/SPEC_SEC_2_2026-11-04.md`만 보고 작성(`t_sec2.py`), `t_sec2_front.py`는 Claude 검증(주소창 토큰 제거·새로고침·XSS, `python t_sec2_front.py dev/harness "http://127.0.0.1:18032/?t=sec2_token_test_12345"`, 서버는 `--token sec2_token_test_12345`) |
| `harness/shot.py` | 1400×900 화면 캡처 |
| `harness/readme_seed.py <데이터 폴더>` | README용 더미 세션·설정·SFTP 파일 생성. 실제 `data/`와 기존 JSON 덮어쓰기 거부 |
| `harness/readme_shots.js` | README 5장 촬영: main(좌우 분할)·sftp·tunnels·palette·settings. lib.js 자동 포함 |

예: `python harness/cdp.py http://127.0.0.1:18022/ harness/t_smoke.js`, `cat harness/lib.js harness/t_3.js | python harness/cdp.py http://127.0.0.1:18022/ -`

README 촬영은 저장소 루트에서 아래 순서로 실행한다(PowerShell). 가짜 SSH와 앱은 각각 별도 콘솔에서 유지하고, 앱 콘솔에 `WEBSSH_DATA`를 지정한다. `start_all.sh`는 다른 데이터를 사용하므로 함께 실행하지 않는다. 재촬영할 때 기존 seed는 그대로 사용한다.

```powershell
python dev/harness/readme_seed.py dev/harness/run/readme_data
# 콘솔 1
python dev/harness/fake_sshd.py 2222 dev/harness/run/readme_data/sftp_root --demo
# 콘솔 2
$env:WEBSSH_DATA=(Resolve-Path dev/harness/run/readme_data).Path
python server.py --no-token --no-tls --port 18022
# 콘솔 3 (Chrome, paramiko, websockets 필요)
New-Item -ItemType Directory -Force docs/images
python dev/harness/shot.py http://127.0.0.1:18022/ docs/images/x dev/harness/readme_shots.js
foreach ($name in 'main','sftp','tunnels','palette','settings') {
    Move-Item -LiteralPath "docs/images/x_$name.png" -Destination "docs/images/$name.png"
}
```

`x_final.png`는 설정 창을 닫고 터널을 중지한 뒤의 보조 캡처다. 촬영에는 2222·18022·18080 포트가 비어 있어야 한다(18081은 중지된 두 번째 터널의 표시용). SSH 비밀번호는 lib.js가 입력하며 저장하지 않는다. 세션 로그·공유 경로·전역 단축키는 seed에서 끈다.

주의: 파이썬 시험(`t_*.py`)은 `WEBSSH_DATA=dev/harness/run/pydata`처럼 시험용 데이터 폴더를 지정할 것 — 없으면 실제 `data/`(known_hosts 등)를 써서 호스트 키 불일치로 실패하거나 실제 데이터를 건드린다(2026-11-04 발생).
주의: 시험을 표준 입력(`-`)으로 넘길 때는 `PYTHONIOENCODING=utf-8`을 붙일 것 — 없으면 시험 안 한글 문자열이 cp949로 깨져 가짜 실패가 난다(2026-11-04 발생).
JS를 파이썬 문자열 안에 넣으면 이스케이프가 깨진다. 파일로 넘기거나 `json.dumps`로 넘길 것.
Claude Code의 Bash 히어독으로 파이썬 코드를 넘기면 `\\`가 한 번 풀려 `"\\n"`이 실제 줄바꿈·NUL로 들어간다(2026-11-04 발생) → 백슬래시가 든 코드는 파일 편집 도구로.
