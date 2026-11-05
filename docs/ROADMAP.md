# 진행표 — 기능 완비 + GUI 압도

목표(사용자 결정 2026-11-03): 기준 도구의 기능 100% 보유 + GUI 가독성·편의성 압도. 모든 기능을 넣되 ⚙설정 "기능 표시"에서 쓸 것만 노출.
기능별 격차·근거는 `GAP.md`(Claude 초안 + agy 2회 교차 검증, 2026-11-03). 시험 도구는 `../dev/`.

## 단계와 상태
| 단계 | 내용 | 상태 |
|---|---|---|
| 0 | 버그: 하이라이트 유령색, 접속 완료 시 모니터링 동기화, 로그 OSC/ST 분할, 비밀번호 창 큐 | ✅ 구현·시험 |
| 1A | 터미널 검색, 붙여넣기 미리보기·위험 명령 경고, 탭 이름·순서·활동 표시, 명령 팔레트, 색 라벨, 기능 표시 설정, SFTP 정렬·숨김·드래그 다운로드, F11, 로그 타임스탬프, 방향키, 사이드바·터널 배지, 호스트 키 교체 화면 | ✅ 구현·시험(`t_1a.js`) |
| 1B | 비밀번호 저장(DPAPI)+RDP 원클릭, 터널 자동 시작, 원격 포워딩, MultiExec, 매크로, Telnet, Serial, SFTP 단독, .ppk·에이전트, 내보내기, 폴더 모두 열기, 로그인 후 명령 | ✅ 구현·시험 (Serial은 실제 COM 장치 미시험) |
| 2 | 점프 호스트 사슬·다중 홉, FTP, VNC(noVNC), 프록시, 키 생성기, TFTP·HTTP 서버, 포트 스캐너, 세션별 터미널 설정, 단축키 설정, 유휴 방지, 터미널 잠금, SFTP 검색 | ✅ 구현·시험(가짜 FTP·VNC 서버) |
| 3 | Mosh(WSL), Rlogin, X11(VcXsrv), 탭 분리, 팝업 터미널(Ctrl+Alt+M), diff, SCP 모드, 이 PC↔원격 두 칸 탐색기, `--session`·바탕화면 바로가기 | 🟡 구현됨. 시험 완료: 이 PC 탭·Rlogin·diff(`t_3.js`), 전역 단축키 등록·해제. 미시험: Mosh·X11(외부 프로그램 필요), 탭 분리, SCP 모드 |
| 4 | 브라우저 내 RDP, XDMCP, 내장 SSH 서버, 패킷 캡처 | ❌ 하지 않음 (2026-11-04 사용자 결정: RDP는 mstsc 실행+SSH 터널 중계 유지, 나머지도 불필요) |

## 리뷰
- 2026-11-03 0~3단계 변경(+4729줄)을 agy(gemini-4-argon-high)·Codex(gpt-6-astra)가 각자 독립 보안 리뷰 → 확인된 결함 20건 + 원격 모드 5건, 오탐 1건. `REVIEW_2026-11-03.md`. 사용자 승인 후 같은 날 25건 모두 수정, 기존 시험(smoke·1A·3) + 수정별 시험 통과. 재리뷰(agy·Codex) 후 회귀·잔여 9건 추가 수정·시험. 남은 항목은 REVIEW 문서 끝.
- 관련 Claude 메모리 사본: `memory/` (협업 방식·이 프로젝트 기록)

- 2026-11-04 잔여 5건(N8·#1·#9·#15·#17) 수정 → Codex·agy 리뷰 → 확인된 결함 D1~D5를 개정 역할(agy 시험 작성 → Codex 구현 → Claude 통합)로 수정·시험. `REVIEW_2026-11-03.md` 끝, 명세 `SPEC_D1-D5_2026-11-04.md`.

## 다음에 이어서 할 일
1. ✅ 11/4 잔여 항목 수정·시험 완료(Codex 구현분 agy 리뷰 결과는 REVIEW 문서). 실환경 미시험: mstsc로 127.77.x.y 접속·자격 증명 자동 사용, 실제 VcXsrv `-auth`(설치 승인 필요)
1-1. 앱 종료 후 `build\apply.ps1`로 새 exe 교체 (빌드는 `build/dist`에 있음)
2. 3단계 미시험 항목 시험
3. ~~4단계~~ 취소 (11/4 결정)
4. ✅ README 기능 목록 갱신 (11/4)
5. GUI 개선 — agy가 UI 메인 리뷰어(스크린샷 판정), Codex 구현, 개선 전 화면 투어 `dev/harness/ui_tour.js`
   - 11/4 시안 A~E 중 **E안 채택**(`docs/design/E_layout.html`). 1단계(배치·디자인, 기존 기능만) 명세 `docs/SPEC_GUI_E1_2026-11-04.md` → ✅ 11/4 통합(브랜치 `feat/gui-e1`, 시험 `dev/harness/t_gui_e1.js`)
   - 2단계(새 기능: 서버 정보 띠, 하단 도크, 스니펫, 명령 기록, 응답 시간 등) ⏳ 1단계 뒤

## 보안 (2026-11-04 진단 → 수정 진행표)
| 단계 | 상태 |
|---|---|
| 1차 진단 `docs/SECURITY_AUDIT_2026-11-04.md`, CVE·CWE `docs/SECURITY_CVE_CWE_2026-11-04.md` | ✅ |
| 1차 수정 (높음 1·2·3, 중간 5·11) `docs/SPEC_SEC_H_2026-11-04.md` | ✅ 커밋 2011b8b |
| 2차 수정 (N1 로컬 토큰, N4 CONNECT, 감사 6 RDP, 7 바로가기, 15 option) | ✅ 11/5 Codex 구현·agy 시험 34/34·agy·Claude 리뷰(중간 2건 추가 수정) |
| Python 업그레이드(N2·N3 CVE-2026-3276) | ✅ 11/5 3.14.10, 빌드 전용 가상환경 build/.venv(PyInstaller 6.22.3 — 6.21은 Tcl 9 zipfs 미지원으로 exe 시작 실패) |
| 남은 중간: 4 DNS 리바인딩, 8 HTTP 공유 심볼릭 링크, 9 응답 크기 제한, 10 동시 작업 제한 / 낮음: 12·13·14(2차에 일부)·N5 | ⏳ v1.0.0 알려진 문제로 공개. 4번은 기본 토큰 도입으로 --no-token 개발 모드에만 해당 |
| exe 재빌드 | ✅ 11/5 build(2), `build/.venv/Scripts/python.exe build/build_exe.py` |

## v1.0.0 릴리즈 (2026-11-05 사용자 결정)
순서: 라이선스 → README·스크린샷 → 보안 2차 + Python 3.14.6 → exe 빌드 → 공개 전 점검(히스토리 내부 정보) → 공개 전환 → 태그 v1.0.0·릴리즈(zip)
| 항목 | 상태 |
|---|---|
| GPL-3.0-or-later 등록 (LICENSE, 앱 라이선스 창) | ✅ 커밋 8887923 |
| README 영어·한국어 + 스크린샷 6장 `docs/SPEC_README_2026-11-05.md` | ✅ 11/5 — 스크린샷 5장(Codex 도구 `dev/harness/readme_*`, Claude 촬영·확인, agy flash 판정), README 초안 Codex(agy argon 한도로 대체)·Claude 검토 |
| 보안 2차 수정, Python 3.14.10 | ✅ 11/5 |
| 공개 전 점검: 히스토리·내부 이름 | ✅ 11/5 공개 저장소는 새 히스토리(커밋 1개), 전체 기록은 비공개 rorena15/web-ssh-terminal-history. 내부 문서(명세·리뷰·메모리 사본·시안)는 추적 제외, 화면 예시·저장소 식별자에서 내부 이름 제거 |
| exe 빌드 → zip → GitHub 릴리즈 v1.0.0, 저장소 공개 | ✅ 11/5 공개 저장소 rorena15/web-ssh-terminal(새로 만듦, 커밋 1개·noreply), 릴리즈 v1.0.0 + W.S.T-v1.0.0-win64.zip(SHA-256 ac42be4a…, 업로드본 해시 일치). 옛 비공개 저장소는 web-ssh-terminal-old로 이름 변경 |
