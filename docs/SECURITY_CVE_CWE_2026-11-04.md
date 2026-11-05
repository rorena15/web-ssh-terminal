# CVE·CWE 진단 2026-11-04 (Codex gpt-6.1-sol, 읽기 전용, 2차)

Claude 판단: N1~N5 중 N1(로컬 모드 토큰 없음) 높음 조건부 — 다음 수정 1순위. 의존성: websockets 17.4로 갱신함, Python 3.14.6 갱신은 승인 대기.

**새 지적은 높음 1건, 중간 3건, 낮음 조건부 1건입니다.** 가장 중요한 추가 사항은 기본 로컬 모드에서 **같은 PC의 다른 OS 계정도 서버 실행 계정 권한으로 로컬 터미널을 열 수 있는 인증 누락**입니다.

파일 수정은 하지 않았습니다. 아래 영향 판정은 정적 코드 기준이며, 실제 EXE·설치 패키지·Windows 공격 재현은 확인하지 못했습니다. `없음`은 **해당 공지의 공격 경로를 발견하지 못했다**는 뜻입니다.

**(A) 의존성 CVE/GHSA**

`L`은 `static/licenses/licenses.json`입니다. 이 파일로 **기록된 버전**은 특정했지만, 실제 설치·배포 버전과의 일치 여부는 미확인입니다.

| 구성요소 | 버전 | 파일 근거 | CVE/GHSA·공식 출처 | 심각도 | 이 코드 영향과 이유 | 조치 |
|---|---|---|---|---|---|---|
| paramiko | 기록 `5.0.0` | `L:34`; `wst/sshconn.py:38`도 5.0 언급 | [CVE-2026-44405](https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2026/44xxx/CVE-2026-44405.json): 4.0.0까지 RSA SHA-1 허용. [공식 변경 이력](https://github.com/paramiko/paramiko/blob/main/sites/www/changelog.rst)에서 5.0의 SHA-1 제거 및 기존 Terrapin 대응 확인 | 낮음 3.4 / Terrapin 중간 | **없음—기록 버전 기준.** SSHClient·키 로딩 사용(`wst/sshconn.py:32`, `:125`, `:134`). SHA-1 문제는 5.0에서 제거됨. Terrapin 방어는 상대 서버의 strict KEX 지원도 필요 | 배포 버전 확인·고정, 상대 SSH 서버도 확인 |
| cryptography | 기록 `49.0.0` | `L:45` | [CVE-2026-69247 / GHSA-g6cj-pr64-35w5](https://github.com/pyca/cryptography/security/advisories/GHSA-g6cj-pr64-35w5): 44.0.0에서 도입, 50.0.0 수정 | 중간 | **없음—해당 API 미사용.** `pkcs7_decrypt_der/pem/smime` 호출 없음. 사용처는 인증서 생성, 키 직렬화, AES-GCM 등(`wst/tls.py:15`, `wst/ppk.py:11`, `wst/vault.py:58`)이며 1차 **16번** 참조 | 50.0.0 이상으로 갱신·고정 |
| cryptography | 동일 | 동일 | [GHSA-m2h6-j472-rp4c](https://github.com/pyca/cryptography/security/advisories/GHSA-m2h6-j472-rp4c), [GHSA-jwv3-5hgf-82ww](https://github.com/pyca/cryptography/security/advisories/GHSA-jwv3-5hgf-82ww): 49.0.0 수정. [GHSA-p423-j2cm-9vmq](https://github.com/pyca/cryptography/security/advisories/GHSA-p423-j2cm-9vmq): 46.0.7 수정. [GHSA-r6ph-v2qm-q3c2](https://github.com/pyca/cryptography/security/advisories/GHSA-r6ph-v2qm-q3c2): 46.0.5 수정 | 낮음~높음 | **없음—기록 버전은 수정 범위.** 자체 X.509 verifier, 비연속 버퍼, SECT 곡선 공격 경로도 발견하지 못함 | 실제 wheel과 버전 대조 |
| cryptography 내 OpenSSL | 별도 버전 불명 | `L:45`에는 OpenSSL 정보 없음 | [CVE-2026-34180 / GHSA-537c-gmf6-5ccf](https://github.com/pyca/cryptography/security/advisories/GHSA-537c-gmf6-5ccf): 공식 wheel은 48.0.1 수정 | 중간 | **없음—공식 49.0.0 wheel이라면. 불명—소스 빌드라면.** 공지는 소스 빌드의 OpenSSL 업데이트를 별도 책임으로 명시 | wheel 출처·연결된 OpenSSL 버전 기록 |
| websockets | 기록 `17.2` | `L:58` | [GHSA-6m5v-9gmr-5665](https://github.com/python-websockets/websockets/security/advisories/GHSA-6m5v-9gmr-5665): `<17.4`, 수정 `17.4` | 중간 5.3 | **있음—기록 버전 기준.** asyncio 서버와 메시지 수신 API 사용. `max_size=4MB`는 빈 continuation 프레임 누적을 막지 못함(`server.py:56`, `:295`; `wst/api.py:569`). 1차 **11번** | 17.4 이상으로 갱신·고정 |
| pywinpty | 기록 `3.1.0` | `L:69` | [공식 PyPI 페이지](https://pypi.org/project/pywinpty/3.1.0/) 확인. 공식 보안 공지 목록은 조회 실패; 대응 CVE/GHSA 확인 못 함 | 불명 | **불명.** `PtyProcess.spawn/read/write/setwinsize`를 실제 사용(`wst/localterm.py:86`, `:89`, `:101`, `:125`). 공지 조회 실패를 안전 판정으로 취급하지 않음 | 배포 wheel·Rust/WinPTY 의존성까지 확인 |
| bcrypt | 기록 `5.0.0` | `L:80` | [공식 공지 목록](https://github.com/pyca/bcrypt/security/advisories)에 공개 공지 없음 | 해당 없음 | **없음—확인한 공지 기준.** 앱의 직접 `hashpw/checkpw` 호출 없음. Paramiko의 암호화 개인키 처리 등 간접 사용은 별도 | 버전·wheel 고정 |
| PyNaCl | 기록 `1.6.2` | `L:91` | [공식 변경 이력](https://github.com/pyca/pynacl/blob/main/CHANGELOG.rst): 1.6.2에서 bundled libsodium의 **CVE-2025-69277** 수정 | 공지에서 점수 미확인 | **없음—공식 bundled 빌드 기준.** 앱은 Paramiko Ed25519 키를 사용(`wst/sshconn.py:32`). 외부 libsodium에 연결한 배포물은 **불명** | bundled/external libsodium 구분·버전 기록 |
| cffi | 기록 `2.1.0` | `L:103` | [공식 공지 목록](https://github.com/python-cffi/cffi/security/advisories)에 공개 공지 없음 | 해당 없음 | **없음—확인한 공지 기준.** 사용자 입력으로 `FFI.cdef/verify/dlopen`을 호출하는 앱 코드는 발견하지 못함 | 간접 의존성으로 고정·추적 |
| pycparser | 기록 `3.0` | `L:114` | [공식 공지 목록](https://github.com/eliben/pycparser/security/advisories). 관련 검색의 [CVE-2025-56005](https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2025/56xxx/CVE-2025-56005.json)는 **PLY의 `yacc(picklefile=…)` 문제이며 disputed** | 관련 PLY 기록은 치명 9.8, 이의 제기 있음 | **없음—앱 경로 기준.** C 파싱·PLY·pickle 로딩 호출 없음. 이를 W.S.T 역직렬화 RCE로 판정할 근거 없음 | 실제 배포물의 PLY 잔존 여부 확인 |
| PyInstaller | **특정 못 함** | `build/build_exe.py:33`에서 실행하지만 버전 기록 없음 | [GHSA-p2xp-xx3r-mffc](https://github.com/pyinstaller/pyinstaller/security/advisories/GHSA-p2xp-xx3r-mffc): `<6.0.0`; [GHSA-9w2p-rh8c-v9g5](https://github.com/pyinstaller/pyinstaller/security/advisories/GHSA-9w2p-rh8c-v9g5): `<5.13.1`; [CVE-2019-16784](https://github.com/pyinstaller/pyinstaller/security/advisories/GHSA-7fcj-pq9j-wh2r): `<3.6` | 높음 | **없음—확인한 빌드 조건 기준.** 첫 공지는 비Windows 파일명 조건, 두 번째는 matplotlib/win32com·권한 상승 등의 조건이 필요하나 해당 사용을 발견하지 못함. 세 번째는 onefile 전용인데 이 코드는 `--onedir`(`build/build_exe.py:33`). **실제 EXE는 불명** | 빌더 버전·부트로더·산출물 SBOM 기록 |
| Python 런타임 | 기록 `3.14.5` | `L:125` | [CVE-2026-3276](https://mail.python.org/archives/list/security-announce@python.org/thread/PP5HB4K7727OBBM76KA2ILID76K3OZGZ/): Unicode 정규화 CPU 고갈. [3.14.6 수정 기록](https://raw.githubusercontent.com/python/cpython/v3.14.6/Misc/NEWS.d/3.14.6.rst) | 중간 | **있음—기록 버전 기준.** `wst/sshconn.py:194`의 `host.encode("idna")`가 정규화를 호출하며 입력 길이 제한 없음. **N3** 참조 | 최소 해당 수정 포함 런타임으로 갱신, 정규화 전 길이 제한 |
| Python 런타임 | 동일 | `server.py:295`, `wst/tls.py:122` | [CPython 보안 이슈 gh-160499](https://github.com/python/cpython/issues/160499): asyncio TLS 내부 응답 누적. CVE/GHSA 식별자는 확인 못 함 | 중간—본 진단 평가 | **있음—정적 도달 경로.** TLS 서버가 해당 계층을 사용하며 HTTP 토큰 검사보다 앞에서 처리됨. 실제 Windows 재현은 미확인. **N2** 참조 | 3.14 브랜치 수정 포함 여부 확인 후 갱신; 단순히 3.14.10으로 해결됐다고 가정하지 말 것 |
| Python 런타임 | 동일 | `server.py:218`, `wst/ftpconn.py:250` 및 import 검색 | 아래 추가 대조 표 참조 | 항목별 상이 | 대부분 **없음**, 일부 배포 환경 **불명** | 현재 보안 수정 포함 런타임으로 재빌드 |
| xterm.js | **특정 못 함** | `L:14`는 `vendored`; `static/vendor/xterm.js:1`에 버전 헤더 없음, `:2`는 source map 경로뿐 | [CVE-2019-0542 공식 기록](https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2019/0xxx/CVE-2019-0542.json), [공식 3.10.1 수정 릴리스](https://github.com/xtermjs/xterm.js/releases/tag/3.10.1) | RCE 공지; 공식 점수 미확인 | **불명.** 원격 출력 파서는 실제 사용(`static/app.js:98`). 정확한 버전·패치 식별 없이 취약/수정 완료를 단정할 수 없음 | 원본 버전·커밋·해시 특정 후 수정본으로 교체 |
| addon-fit | **특정 못 함** | `static/vendor/addon-fit.js:1`; `L:13`은 통합 명칭만 기록 | [xterm 공식 공지 목록](https://github.com/xtermjs/xterm.js/security/advisories)에서 별도 대응 공지 확인 못 함 | 해당 없음 | **불명—출처 추적 부족.** `static/app.js:103`에서 사용. 확인한 알려진 CVE는 없음 | xterm과 별도로 버전·해시 기록 |
| addon-web-links | **특정 못 함** | `static/vendor/addon-web-links.js:1`; 버전 헤더 없음 | [xterm 공식 공지 목록](https://github.com/xtermjs/xterm.js/security/advisories)에서 별도 대응 공지 확인 못 함 | 해당 없음 | **불명—출처 추적 부족.** 실제 사용(`static/app.js:105`). 현 코드의 기본 패턴은 HTTP(S), 새 창 `opener=null` 처리 존재 | 버전·해시 기록 |
| noVNC | **특정 못 함** | `L:23`은 `vendored`; `core/rfb.js:3`의 저작권 연도는 버전 근거가 아님 | [CVE-2017-18635 / GHSA-49rv-g7w5-m8xx](https://github.com/advisories/GHSA-49rv-g7w5-m8xx): `<0.6.2`, 수정 `0.6.2` | 중간 | **없음—이 공지의 UI 경로 기준.** 취약 공지는 `include/ui.js`, `vnc_auto.html`, `vnc.html`의 원격 문자열 HTML 삽입. 이 앱은 RFB 모듈을 직접 사용하며 desktop name은 `title`에 대입(`static/vnc.js:7`, `:57`, `:82`). 그 밖의 버전 판정은 **불명** | 원본 태그·커밋 특정 |
| pako | **1.0.3 기반 수정본**; 정확한 수정 리비전 불명 | `static/vendor/novnc/vendor/pako/README.md:1–2` | [공식 공지 목록](https://github.com/nodeca/pako/security/advisories)에 공개 공지 없음 | 해당 없음 | **없음—확인한 공지 기준.** 실제 inflate/deflate 사용(`core/inflator.js:9`, `:50`; `core/deflator.js:9`). C zlib CVE를 그대로 적용할 근거 없음. 버전 관리 문제는 1차 **16번** | noVNC의 수정 이력·해시까지 추적 |

Python 추가 대조 결과입니다. **해당 API를 사용한다는 이유만으로 CVE의 추가 발동 조건까지 충족한다고 판단하지 않았습니다.**

| 공식 출처·항목 | 이 사본 판정 |
|---|---|
| [CVE-2026-9669](https://mail.python.org/archives/list/security-announce%40python.org/message/DBJZETMGUIFK7DVUWMOXHD3Z6IX2QPSX/), bz2 오류 후 재사용 | **없음.** 해당 decompressor 사용 없음 |
| [CVE-2026-7210·CVE-2026-8328](https://mail.python.org/archives/list/security-announce%40python.org/2026/5/), XML hash flooding·`ftpcp()` PASV SSRF | **없음.** XML 파서·`ftpcp()` 사용 없음. 일반 `FTP/FTP_TLS` 사용과 구분 |
| [CVE-2026-7774·11940](https://mail.python.org/archives/list/security-announce%40python.org/latest?count=10&page=3), tar 추출 우회 | **없음.** tar 추출 없음 |
| [3.14.8 보안 목록](https://www.python.org/downloads/release/python-3148/): CVE-2026-19445, 19553, 15310, 19672, 15806, 17084 | 각각 **없음**: SNI context 교체 없음 / 공격자 제공 `server_hostname`으로 `wrap_bio()` 호출 없음 / ZIP 압축 해제 없음 / tar 추출 없음 / `HTTPPasswordMgr` 없음 / stringprep를 접근 제어 정책으로 쓰는 경로 없음 |
| [GHSA-w4q2-g22w-6fr4 관련 공식 이슈](https://github.com/python/cpython/issues/150743), HTTP 응답 무한 처리 | **제한적 영향 가능·낮음.** `server.py:218`의 기존 로컬 서버 탐지에서 `urlopen().read()` 사용. 악성 로컬 포트 점유자가 시작을 지연시키는 시나리오는 **추측**, 미재현 |
| [CVE-2026-115557·114583](https://www.python.org/downloads/release/python-31410/) | eMudhra CA 문제는 **설치·trust store 환경 불명**. 앱의 외부 인증서 검증 경로로 확정하지 못함. tar 항목은 **없음** |

**(B) 1차 지적 1–16의 CWE 매핑**

위치는 현재 사본의 `wst/` 구조 기준입니다. 기존 결함 설명·조치는 반복하지 않았습니다.

| 1차 번호 | 주 CWE | 보조 CWE / 분류 이유 | 근거 위치 |
|---|---|---|---|
| 1 | CWE-79 | DOM XSS | `wst/term.py:104`, `static/app.js:490`, `:492` |
| 2 | CWE-918 | CWE-862: 금지된 로컬 대상 검사 누락 | `wst/sshconn.py:124`, `:134`, `:226` |
| 3 | CWE-295 | 인증서 검증 누락 | `wst/ftpconn.py:250` |
| 4 | CWE-346 | 신뢰할 수 없는 Host로 Origin 허용값 구성 | `server.py:129–132` |
| 5 | CWE-367 | 결과적으로 CWE-918 우회 | `wst/common.py:32`, `wst/rawterm.py:244`, `wst/vncproxy.py:35` |
| 6 | CWE-93 | CR/LF로 RDP 설정 줄 주입 | `wst/api.py:169–188` |
| 7 | CWE-88 | 인수 주입. OS 셸 명령 주입 CWE-78로 단정하지 않음 | `wst/api.py:337`, `:340` |
| 8 | CWE-59 | 링크 해석 후 공유 경계 이탈 | `wst/tools.py:232–238` |
| 9 | CWE-770 | 제한 없는 메모리 할당·수집 | `wst/sftp.py:80–84`, `:319–326`; `wst/rawterm.py:60–71` |
| 10 | CWE-770 | 작업·연결·전송 수 제한 부재 | `wst/api.py:576`, `wst/tools.py:154`, `:197–209` |
| 11 | CWE-770 | CWE-1395: 알려진 취약 의존성 사용 | `L:58`, `server.py:295` |
| 12 | CWE-459 | 자격 증명 정리 미완료 | `wst/api.py:286–307`, `wst/vault.py:207–217` |
| 13 | CWE-312 | 비밀 필드의 평문 저장 | `wst/api.py:438`, `static/tree.js:519–526` |
| 14 | CWE-598 | CWE-532: URL 및 로그에 인증 비밀 기록 | `server.py:299–302`, `static/core.js:9` |
| 15 | CWE-79 | HTML 속성 문맥 이스케이프 누락. 실행 가능성은 기존대로 미확인 | `static/tree.js:331`, `:341`, `:370`; `static/tunnels.js:93` |
| 16 | 직접 대응 없음 | 버전·출처 목록 부족은 관리 문제. **취약 구성요소가 확인된 부분에만 CWE-1395** 적용 가능 | `L:14`, `:23`; pako `README.md:2` |

**(C) 1차에 없던 새 지적**

| 번호 | 심각도 | CWE | 위치 | 내용 | 시나리오 | 고칠 방법 |
|---|---|---|---|---|---|---|
| **N1** | **높음—다중 OS 계정 환경 조건부** | **CWE-306** | `server.py:102–106`, `:129–132`, `:283–288`; `wst/localterm.py:55`, `:88–90` | 기본 루프백 실행에서는 토큰이 없고 로컬 터미널이 활성화됨. Origin은 임의 클라이언트가 지정할 수 있으므로 **OS 사용자 인증이 되지 않음** | 같은 PC의 다른 저권한 계정이 직접 WebSocket 클라이언트로 허용 Origin을 보내 `/local`에 연결. 자식 셸은 W.S.T 실행 계정 권한으로 생성됨. 관리자 실행이면 권한 상승 가능. **정적 경로 확인, 실제 계정 간 재현 미실행.** 1차 4번과 관련되지만 DNS·브라우저가 필요 없는 별도 공격 경로 | 로컬 모드도 기본 인증 필수. OS 계정 간 격리가 필요하면 사용자 SID를 확인하는 통신 경계 검토 |
| **N2** | **중간—런타임 조건부** | **CWE-770** | `L:125`; `server.py:295`; `wst/tls.py:123–125` | [CPython gh-160499](https://github.com/python/cpython/issues/160499)의 asyncio TLS 응답 누적 경로 사용. HTTP 토큰·Origin·WebSocket 크기 제한보다 아래 계층 | 접속자가 TLS 연결 후 읽기를 멈추고 내부 TLS 응답을 발생시키면 출력 MemoryBIO가 누적될 수 있음. **Windows 실제 영향은 추측·미재현.** 공식 재현은 Linux/main이며 3.14 수정도 존재 | gh-160499 수정이 포함된 런타임/배포 패치 확인. 연결·메모리 제한 병행. **1차 11번과 다른 TLS 계층 문제** |
| **N3** | **중간—기록 런타임 기준** | **CWE-407** | `L:125`; `wst/sshconn.py:194`; 입력 경로 `:237`, `:253` | **CVE-2026-3276**에 도달 가능한 무제한 IDNA 변환. [3.14.5 IDNA 구현](https://raw.githubusercontent.com/python/cpython/v3.14.5/Lib/encodings/idna.py)은 길이 최종 거부 전에 `nameprep()`의 NFKC 정규화를 실행 | SOCKS 프록시를 사용하는 연결 요청의 host에 긴 결합문자열을 제공. DNS 이름이 최종 거부되더라도 먼저 과도한 CPU를 사용할 수 있음. **API 연결은 확인, 부하·응답 지연은 미측정** | 수정 런타임 사용. 정규화 전에 전체 host·각 label 입력 길이 제한. 4MB WebSocket 제한만으로 충분하다고 보지 말 것 |
| **N4** | **중간—악용 결과 조건부** | **CWE-93** | `wst/sshconn.py:153–165`; 전달 `:237`, `:253` | HTTP CONNECT의 요청줄·Host에 host/port를 CR/LF 검사 없이 직접 삽입 | 악성 가져오기 설정 또는 API 입력으로 헤더·요청 경계 바이트 삽입. **삽입 문자열 생성은 확인.** 실제 요청 분할·프록시 정책 우회는 프록시 파서에 따라 달라 **추측·미재현** | host에서 제어문자·공백 및 잘못된 authority 거부, port를 먼저 정수·범위 검증. IPv6 authority도 별도 구성 |

낮음은 별도 기록합니다.

| 번호 | 심각도 | CWE | 위치 | 내용 | 시나리오 | 고칠 방법 |
|---|---|---|---|---|---|---|
| **N5** | **낮음—실제 ACL 미확인** | **CWE-252**, 조건부 **CWE-276** | `wst/tools.py:305–311`; `wst/tls.py:48–51`, `:69–70`; `wst/x11.py:70–71` | SSH 개인키를 먼저 쓰고 `icacls`의 실패 종료 코드를 무시함. CA 개인키·X11 쿠키는 별도 접근 권한 제한 없이 상속 권한에 의존 | 넓은 읽기 권한을 상속한 저장 위치나 ACL 적용 실패 시 다른 계정이 비밀 파일을 읽을 수 있음. **이 사본의 실제 파일 권한이 넓다는 증거는 없음** | 보호된 디렉터리에서 생성하고 ACL 성공을 확인. 실패 시 성공 응답하지 말고 정리·오류 처리. CA 키·쿠키도 권한 정책 명시 |

**(D) 최신 CWE Top 25 점검 요약**

조회 시 공식 최신판은 [**2025 CWE Top 25**](https://cwe.mitre.org/top25/archive/2025/2025_cwe_top25.html)입니다. `해당 없음`은 검토한 앱 코드 경로 기준이며, 네이티브 의존성 전체의 메모리 안전성을 증명한 결과는 아닙니다.

| 순위 | CWE | 점검 결과 |
|---:|---|---|
| 1 | CWE-79 XSS | **기존 1·15번**. 추가 확정 XSS 없음 |
| 2 | CWE-89 SQL 삽입 | **해당 없음**. DB·SQL 실행 경로 발견 못 함 |
| 3 | CWE-352 CSRF | 일반 외부 Origin은 거부(`server.py:129`). **기존 4번**, 추가 확정 없음 |
| 4 | CWE-862 인증 후 권한 검사 누락 | **기존 2번**. 로컬 전용 API 차단도 확인(`wst/api.py:490`) |
| 5 | CWE-787 범위 밖 쓰기 | 앱 코드에서 **해당 없음**. ctypes 길이 사용 검토; 네이티브 내부는 별도 범위 |
| 6 | CWE-22 경로 탐색 | 정적·TFTP 경계 검사 존재(`server.py:144`, `wst/tools.py:136`). 링크 문제는 **기존 8번** |
| 7 | CWE-416 해제 후 사용 | 앱에서 직접 관리하는 네이티브 메모리의 새 결함 **발견 못 함** |
| 8 | CWE-125 범위 밖 읽기 | 새 결함 **발견 못 함**. Python slicing은 해당 네이티브 오류와 구분 |
| 9 | CWE-78 OS 명령 삽입 | 추가 확정 없음. `shlex.quote`, 공개키 정규식 검증 확인(`wst/fsadapt.py:69`, `wst/api.py:478`). **기존 7번은 CWE-88** |
| 10 | CWE-94 코드 삽입 | **해당 없음**. 외부 입력 `eval/exec` 경로 없음; 의도된 터미널 실행 기능과 구분 |
| 11 | CWE-120 크기 검사 없는 버퍼 복사 | 앱에서 새 결함 **발견 못 함**. Python 및 ctypes 버퍼 크기 사용 검토 |
| 12 | CWE-434 위험 파일 업로드 | **해당 없음**. 일반 파일 전송 기능이며 서버 측 스크립트 실행 경로 없음. TFTP 쓰기는 명시적 선택(`wst/tools.py:192`) |
| 13 | CWE-476 NULL 역참조 | 새 보안 결함 **발견 못 함**. Python 예외와 네이티브 NULL 역참조를 구분 |
| 14 | CWE-121 스택 버퍼 오버플로 | 앱에서 **해당 없음**. Python bz2 공지는 A의 API 미사용 판정 참조 |
| 15 | CWE-502 위험한 역직렬화 | **해당 없음**. JSON 사용; pickle·marshal·unsafe YAML 호출 없음 |
| 16 | CWE-122 힙 버퍼 오버플로 | 새 결함 **발견 못 함**. 메모리 고갈 **기존 9–11번·N2**와 구분 |
| 17 | CWE-863 잘못된 권한 검사 | **기존 2·4·5번 관련**. 추가 확정 없음 |
| 18 | CWE-20 입력 검증 부족 | **기존 6·7·15번**, 신규 **N3·N4**. 각각 구체적인 CWE로 분류 |
| 19 | CWE-284 접근 제어 | **기존 2·8번**, 신규 **N1**. 동일 토큰이 공유 권한 주체인 구조 확인 |
| 20 | CWE-200 정보 노출 | **기존 12–14번**, 조건부 **N5**. 추가 비밀 자료는 열지 않음 |
| 21 | CWE-306 중요 기능 인증 누락 | **신규 N1**. HTTP/TFTP 공유의 무인증은 UI에 명시된 공유 기능(`static/tools.js:110–111`)이므로 별도 결함으로 추가하지 않음 |
| 22 | CWE-918 SSRF | **기존 2·5번**. 임의 원격 접속이라는 제품 기능 자체는 결함으로 취급하지 않음 |
| 23 | CWE-77 명령 삽입 | **기존 7번의 인수 주입**. 추가 OS 셸 삽입 확정 없음 |
| 24 | CWE-639 사용자 제어 키에 의한 권한 우회 | **추가 발견 없음**. 세션 ID는 무작위(`wst/ftpconn.py:297` 등), 토큰별 별도 사용자 소유권 모델은 없음 |
| 25 | CWE-770 자원 할당 제한 부재 | **기존 9–11번**, 신규 **N2**. **N3은 알고리즘 복잡도 CWE-407** |

Top 25 밖의 요청 항목도 점검했습니다.

- **CWE-798 하드코딩 자격 증명:** 운영 코드에서 발견하지 못했습니다. DPAPI entropy·프로토콜 상수는 계정 비밀번호로 분류하지 않았습니다.
- **CWE-269·276 권한 관리:** 앱 자체 권한 상승 기능은 발견하지 못했습니다. **N1**의 실행 계정 권한 승계와 **N5**의 조건부 파일 권한 문제를 기록했습니다.
- **CWE-494 무결성 검증 없는 코드 다운로드:** 검토한 운영·빌드 코드에서 다운로드한 코드를 자동 실행하는 경로는 발견하지 못했습니다. 설치 배치 파일·실제 배포물은 이 사본에서 확인하지 못했습니다. 의존성 고정 부족은 **1차 16번** 참조입니다.

**실행·검증 기록과 한계**

| 명령·작업 | 실제 결과 |
|---|---|
| `rg --files`, `rg -n`, `Get-Content`로 지정 소스·라이선스·이전 진단 읽기 | 버전 기록, 입력 전달 경로, API 사용처 확인. 일부 출력은 콘솔 인코딩 때문에 한글이 깨짐 |
| 공식 CVE 기록·유지관리자 공지·CPython 변경 이력 조회 | 위 URL과 대조. 일부 공지 페이지는 조회 실패로 명시 |
| 추출한 `proxy_socket()`을 mock으로 검증하려던 `python -B -` | **실패, 종료 코드 1**. 실행 파일 접근 오류. Python 실행 검증으로 계산하지 않음 |
| 첫 PowerShell 보조 검증 | 형식 문자열·제한 언어 오류로 실패 |
| 수정한 순수 PowerShell 문자열 구성 | `injected_header_count=2`; 네트워크·앱 실행 없음. **실제 프록시 악용 증명이 아님** |
| `git -c core.fsmonitor=false status --short --untracked-files=normal` | 종료 코드 `0`; `?? AUDIT_PREV.md`와 전역 ignore 접근 경고. 해당 파일은 작업 시작 때 이미 존재했고, 추적 파일 변경 출력은 없음 |

실제 `data/`, 인증서·개인키·로그·자격 증명 및 지정 금지 자료는 읽지 않았습니다. EXE·설치 환경, NTFS ACL, 계정 간 접속, 프록시 동작, TLS·Unicode 부하 공격은 재현하지 않았습니다.