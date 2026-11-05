# 보안 진단 2026-11-04 (Codex gpt-6.1-sol, 읽기 전용, 구조 정리 전 경로 기준)

Claude 확인(코드): 1 app.js:490-492 innerHTML에 Load 원격값 / 2 sshconn 직접 연결에 자기 PC 주소 검사 없음 / 3 ftpconn.py:250 FTP_TLS context 없음 / 6 api.py:174 username 그대로 .rdp 줄 / 7 api.py:337 --session "{sid}" 수동 인용 / 11 설치된 websockets 17.2. 나머지는 진단 원문 근거.

구조 정리 후 경로: 파이썬 모듈은 wst/ 아래.

읽기 전용 진단 결과, **가장 우선할 문제는 원격 모니터링 XSS, 원격 모드의 로컬 SSH 접근, FTPS 인증서 검증 누락**입니다. 파일은 수정하지 않았습니다.

아래는 정적 코드와 제한된 메모리 내 실행으로 확인한 결과입니다. 실제 브라우저·서버에서 공격을 완료한 것은 아니며, 환경에 따라 달라지는 부분은 **추측**으로 표시했습니다.

**치명: 확정한 항목 없음.**

**높음**

| 번호 | 심각도 | 위치 | 취약점 | 공격 시나리오 | 고칠 방법 |
|---|---|---|---|---|---|
| 1 | 높음 | `term.py:104`, `static/app.js:490`, `static/app.js:492` | **원격 모니터링 출력으로 DOM XSS**. Load 값은 원격 출력의 첫 세 토큰을 그대로 전달하고, 프런트에서 HTML로 삽입함 | 악성 SSH 서버가 모니터링 명령에 정상 형식의 응답을 주면서 loadavg 자리에 `<img/src=x/onerror=alert(1)>`를 반환. 모니터링이 켜진 탭을 보면 스크립트 실행 가능. 로컬 모드에서는 같은 출처의 `/local`에 접근하여 PC 명령 실행으로 이어질 수 있음 | 서버에서 Load 값을 유한한 숫자로 검증하고, 프런트에서는 `textContent` 또는 이스케이프 사용. CSP도 추가 |
| 2 | 높음 | `sshconn.py:124`, `sshconn.py:134`, `sshconn.py:226`, `term.py:205` | **직접 SSH 연결 및 첫 SSH 홉에 자기 PC 주소 검사 누락**. 주소 검사는 프록시 연결에만 있음 | 원격 토큰 보유자가 `/ws?t=…`에 `host=127.0.0.1`인 연결 요청. 로컬 SSH 서비스와 유효한 인증 수단이 있으면 로컬 셸·SFTP 사용 가능. 로컬 SSH를 게이트웨이로 삼으면 차단된 VNC/Telnet 접근도 우회 가능 | 소켓을 직접 여는 모든 최초 SSH 연결에 공통 대상 검사를 적용. 프록시·점프 사용 여부와 실제 접속 지점을 기준으로 검사 |
| 3 | 높음 | `ftpconn.py:248`–`256` | **FTPS 서버 인증서·호스트 이름 검증 누락**. `FTP_TLS`에 검증용 context를 전달하지 않음 | 네트워크 공격자가 위조 FTPS 서버로 중계하면 비밀번호와 파일 내용을 탈취·변조할 수 있음. 데이터 암호화 `prot_p()`만으로 서버 신원은 보장되지 않음 | `FTP_TLS(context=ssl.create_default_context(), timeout=15)` 사용. 사설 인증서는 명시적 CA 또는 인증서 고정으로 처리 |

3번은 CPython 3.14의 기본 동작을 확인했습니다. `FTP_TLS`의 기본 context는 인증서 검증을 하지 않는 context입니다. [CPython ftplib 구현](https://raw.githubusercontent.com/python/cpython/3.14/Lib/ftplib.py), [ssl 기본 context 구현](https://raw.githubusercontent.com/python/cpython/3.14/Lib/ssl.py)

**중간**

| 번호 | 심각도 | 위치 | 취약점 | 공격 시나리오 | 고칠 방법 |
|---|---|---|---|---|---|
| 4 | 중간 | `server.py:129`–`132`, `server.py:282` | **Origin 검사가 요청의 Host만 신뢰하여 DNS 리바인딩 방어가 불완전** | **추측·브라우저 조건부:** 토큰 없는 로컬 `--no-tls` 실행에서 공격 도메인을 로컬 주소로 재해석시키면 Host와 Origin이 함께 공격 도메인이므로 검사 통과 가능. 기본 HTTPS에서는 인증서 이름 검사, Chrome에서는 로컬 네트워크 접근 정책이 추가 장애물 | 허용 Host·Origin을 서버 설정으로 고정하고 실제 스킴도 일치시킬 것. 로컬 실행에도 토큰 사용 |
| 5 | 중간 | `common.py:32`, `rawterm.py:244`–`245`, `vncproxy.py:35`–`36`, `sshconn.py:157`–`158`, `ftpconn.py:252`–`253` | **주소 검사 후 연결 시 DNS를 다시 조회하는 TOCTOU** | 원격 토큰 보유자가 제어하는 DNS가 검사에는 외부 주소, 실제 연결에는 루프백 주소를 반환하면 Telnet·VNC·프록시·FTP의 자기 PC 차단 우회 가능. DNS 캐시 등에 따른 실환경 재현은 미확인 | 검증한 IP로 직접 연결하고 peer 주소 확인. 자기 PC 주소 목록도 호스트 이름 조회만이 아닌 인터페이스 기준으로 수집 |
| 6 | 중간 | `api.py:169`–`188`, `static/tree.js:514`–`526` | **RDP 파일 줄바꿈 주입**. host·username을 `.rdp` 설정 줄에 직접 삽입 | 가져오기 JSON의 username을 `u\r\ndrivestoredirect:s:*`로 지정하고 해당 RDP를 실행하면, UI에서 드라이브 공유가 꺼져 있어도 추가 설정이 파일에 기록됨. mstsc 실제 적용은 미실행 | host·username의 CR/LF 및 제어문자 거부. 가져오기와 API 저장 단계 모두 스키마 검증 |
| 7 | 중간 | `api.py:336`–`340`, `static/tree.js:519` | **바로가기의 세션 ID로 실행 옵션 주입** | 가져온 ID가 `x" --host 0.0.0.0 --no-tls --token "known`이면 최종 인수 문자열에 추가 옵션이 들어감. 사용자가 바로가기를 생성하고 서버가 종료된 뒤 실행하면 의도하지 않은 원격·평문 실행 가능. 실제 `.lnk` 실행은 미검증 | ID 형식을 UUID 등으로 제한. 문자열을 수동 인용하지 말고 Windows 인수 인코딩 적용 |
| 8 | 중간 | `tools.py:232`–`238` | **HTTP 공유 폴더의 링크를 따라 범위 밖 파일 제공** | HTTP 공유 루트 안에 외부 폴더를 가리키는 심볼릭 링크·정션이 있으면, 네트워크 사용자가 그 경로로 공유 범위 밖 파일을 받을 수 있음 | 각 요청의 최종 해석 경로가 공유 루트 내부인지 검사하고 외부 reparse 경로 차단 |
| 9 | 중간 | `sftp.py:80`–`84`, `sftp.py:319`–`326`, `sshconn.py:295`–`296`, `rawterm.py:60`–`71` | **원격 데이터의 무제한 메모리 수집** | 악성 SFTP/FTP 서버가 작은 stat 크기를 알린 뒤 대량 데이터를 보내면 다운로드·편집 제한 우회. 악성 SSH 명령 출력도 전체 `read()`로 수집. Telnet은 종료되지 않는 SB 데이터를 계속 축적 | 실제 읽은 바이트 기준 강제 상한, 제한 길이 읽기, 전체 작업 시간 제한. Telnet SB 길이 제한 |
| 10 | 중간 | `api.py:575`, `tools.py:154`, `tools.py:171`, `tools.py:197`–`209`, `tunnels.py:251` | **동시 작업·연결·TFTP 전송량 제한 부족** | 토큰 보유자가 API 요청을 반복하면 작업이 계속 생성됨. TFTP를 네트워크에 열었을 때는 무인증 사용자가 스레드를 다수 만들거나, 쓰기 허용 시 큰 업로드를 메모리에 축적시킬 수 있음 | 전역·연결별 동시성 제한, 작업 큐와 취소 처리, 전송량·시간 제한. TFTP 업로드는 제한된 임시 파일로 스트리밍 |
| 11 | 중간 | `static/licenses/licenses.json:58`, `server.py:295` | **기록된 websockets 17.2가 알려진 메모리 고갈 취약점 범위에 포함** | 연결 후 빈 비최종 continuation 프레임을 계속 보내면 미완성 메시지의 프레임 목록이 증가. `max_size=4MB`로 막히지 않음. 원격 모드에서는 토큰 필요. 실제 설치 버전과 공격 실행은 미확인 | **websockets 17.4 이상**으로 갱신하고 버전 고정. 수신 작업에도 시간·자원 제한 |

8번의 링크 추적은 Python 공식 문서에 명시된 동작입니다. [HTTP 서버 보안 고려사항](https://docs.python.org/3.14/library/http.server.html#security-considerations)

11번은 2026-10-30 공개된 **GHSA-6m5v-9gmr-5665**이며, 영향 범위는 `<17.4`, 수정 버전은 `17.4`입니다. [공식 보안 공지](https://github.com/python-websockets/websockets/security/advisories/GHSA-6m5v-9gmr-5665)

**낮음 — 별도 기록**

| 번호 | 심각도 | 위치 | 취약점 | 공격 시나리오 | 고칠 방법 |
|---|---|---|---|---|---|
| 12 | 낮음 | `api.py:286`–`297`, `vault.py:207`–`217` | **직결 RDP 자격 증명은 mstsc 종료 후 삭제하지 않음**. 정리 스레드는 게이트웨이 연결에만 생성됨 | 직결 RDP 종료 또는 자격 증명 등록 이후 실행 실패에도 `TERMSRV/host`가 Windows 로그온 세션 동안 남음. vault 잠금으로도 삭제되지 않음 | 직결도 프로세스 수명에 맞춰 정리하고, 실행 실패 시 롤백. 기존 자격 증명 처리 정책도 정의 |
| 13 | 낮음 | `static/tree.js:519`–`526`, `api.py:436`–`438`, `static/palette.js:156` | **JSON 가져오기·저장·내보내기가 비밀 필드를 제거하지 않음** | 가져오기 JSON에 password·passphrase·key 또는 중첩 proxy 비밀번호가 있으면 일반 sessions JSON에 평문 저장되고 다시 내보내짐. 정상 UI의 분리 저장과 다른 경로 | 서버에서 허용 필드만 저장하고 비밀 필드를 재귀적으로 제외. 가져오기·내보내기에도 같은 규칙 적용 |
| 14 | 낮음 | `server.py:48`–`52`, `server.py:299`–`302`, `static/core.js:9` | **접속 토큰이 URL과 실행 로그에 남음** | 창 없는 원격 실행에서는 토큰 포함 URL이 `data/server.log`에 기록됨. URL은 브라우저 기록에도 남을 수 있음. 재사용한 지정 토큰이면 과거 기록도 유효 | 로그에서 토큰 제외. 초기 인증 후 URL을 정리하고 가능하면 보호된 세션 쿠키 사용 |
| 15 | 낮음 | `static/tree.js:331`, `static/tree.js:341`, `static/tree.js:370`, `static/tunnels.js:93` | **가져온 세션·매크로 ID의 HTML 속성 이스케이프 누락** | ID의 `"`로 `option value` 속성을 탈출해 추가 속성·마크업 삽입 가능. **스크립트 실행은 추측:** select/option의 브라우저별 이벤트 동작을 재현하지 않았음 | `new Option(label, id)` 또는 DOM 속성 대입 사용. ID 형식 검증 병행 |

**정보**

| 번호 | 심각도 | 위치 | 취약점 | 공격 시나리오 | 고칠 방법 |
|---|---|---|---|---|---|
| 16 | 정보 | `static/licenses/licenses.json:14`, `:23`, `:45`; `static/vendor/novnc/vendor/pako/README.md:2`; `실행(콘솔).bat:5` | **의존성 출처·버전 추적 부족**. xterm/noVNC는 `vendored`, pako는 1.0.3 기반. 설치 스크립트에는 버전 고정 없음 | vendored 코드의 정확한 취약 버전 대조가 불가능함. 기록된 cryptography 49.0.0에는 PKCS#7 복호화 공지가 적용되지만, 이 사본에서 해당 API 호출은 발견하지 못해 W.S.T의 공격 경로로 판정하지 않음 | vendored 버전·커밋·해시와 잠금 의존성 목록을 기록하고 실제 배포물과 대조 |

cryptography의 해당 문제는 PKCS#7 복호화 API에 관한 **CVE-2026-69247**, 수정 버전은 50.0.0입니다. CA 생성 코드의 취약점으로 연결할 근거는 찾지 못했습니다. [공식 보안 공지](https://github.com/pyca/cryptography/security/advisories/GHSA-g6cj-pr64-35w5)

**실행한 확인과 실제 결과**

- `rg --files --hidden …`, `rg -n …`으로 파일 목록과 호출 경로를 검사했습니다. 애플리케이션은 import하거나 실행하지 않았습니다.
- PowerShell here-string을 `node`에 전달하여 소스에서 추출한 `renderStatus()`를 모의 DOM으로 실행했습니다. 실제 출력에 다음 문자열이 그대로 포함됐습니다.

```text
Load <img/src=x/onerror=alert(1)> 0 0
```

이는 **HTML 삽입 경로 확인**이며, 실제 Chrome의 이벤트 실행 시험은 아닙니다.

- `git -c core.fsmonitor=false status --short --untracked-files=normal`: 종료 코드 `0`, 변경 항목 출력 없음. 사용자 전역 ignore 파일 접근 경고는 발생했습니다.

**확인됨(안전) — 코드 기준**

- 모든 등록 WebSocket 경로와 `/dl/`에 공통 토큰 검사가 있습니다. 일반적인 다른 출처 WebSocket 요청과 Origin 없는 요청은 거부합니다. `server.py:102`, `:113`, `:126`
- 원격 모드의 로컬 터미널·localfs·Serial·개인키 파일·SSH agent·X11 및 후반부 로컬 API 차단을 확인했습니다. 저장 vault 자동 사용도 차단됩니다. `localterm.py:55`, `fsadapt.py:270`, `rawterm.py:195`, `sshconn.py:50`, `:138`, `term.py:210`, `api.py:489`, `vault.py:184`
- 원격 포워딩 시작은 원격 모드에서 거부하고, 로컬·동적 터널은 IPv4 루프백에만 바인딩합니다. `api.py:456`, `tunnels.py:88`
- 정적 파일과 TFTP의 일반 경로 탈출은 `resolve()` 후 루트 포함 검사로 막습니다. 로그 이름은 구분자·제어문자·끝의 점을 정리합니다. `server.py:144`, `tools.py:136`, `term.py:27`
- 서버 간 복사에서 Windows 대상 이름의 `/`, `\`, `:`, NUL 및 `.`·`..`를 거부합니다. `sftp.py:214`
- SSH TOFU 최초 승인과 기존 키 불일치 거부 경로가 있습니다. 자동 수락 정책은 사용하지 않습니다. `sshconn.py:77`, `:124`, `:273`
- vault 디스크 저장은 DPAPI, 선택적 마스터 암호는 scrypt와 AES-GCM을 사용합니다. 일반 vault 응답에는 비밀번호가 포함되지 않습니다. `vault.py:36`, `:53`, `:99`, `:109`
- RDP 비밀번호는 프로세스 인수가 아닌 CredWrite로 전달합니다. 게이트웨이는 세션별 `127.77.x.y` 주소와 종료 시 자격 증명 삭제를 사용합니다. `vault.py:207`, `api.py:196`, `:297`
- X11 가짜 쿠키 비교·교체, 인증 필드 길이 제한과 `-auth` 사용을 확인했습니다. `x11.py:83`, `:124`
- 일반 파일명·세션명·오류·VNC 서버 이름은 확인한 표시 경로에서 이스케이프 또는 텍스트 속성을 사용합니다. 터미널 링크 addon은 HTTP(S)만 탐지하고 새 창의 `opener`를 제거합니다. `static/app.js:494`, `static/core.js:329`, `static/vnc.js:80`, `:82`, `static/vendor/addon-web-links.js:1`
- TLS 최소 버전 1.2와 critical CA Name Constraints 설정이 있습니다. 실제 Windows·Chrome의 제약 적용은 별도 검증 대상입니다. `tls.py:66`, `:124`

**진단하지 못한 범위**

- 실제 EXE·설치 패키지 버전, Chrome 정책, 방화벽, DNS 캐시, NTFS ACL·정션 동작, mstsc·CredWrite의 실제 수명은 시험하지 않았습니다.
- 실제 `data/`, 인증서 개인키, 로그, 자격 증명 등 사용자 자료는 열지 않았습니다. 따라서 배포 환경에서의 비밀 노출 여부는 확인하지 못했습니다.
- vendored 라이브러리 전체의 독립적인 코드 감사와 부하·메모리 고갈 시험은 수행하지 않았습니다.
- 터미널 출력은 평문 로그에 남습니다. 출력에 나타난 비밀의 자동 제거는 없으며, vault 잠금도 기존 터널·FTP·브라우저 객체에 남은 비밀을 모두 지우는 기능은 아닙니다.
- 제시한 재현 입력 중 실제 브라우저·네트워크·Windows 실행이 필요한 항목은 후속 재현이 필요합니다.