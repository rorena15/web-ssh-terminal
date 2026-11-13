# Security Policy / 보안 정책

[English](#english) | [한국어](#한국어)

## English

### Supported versions

Only the latest release receives security fixes.

| Version | Supported |
|---|---|
| 1.1.x | Yes |
| 1.0.x | No. Upgrade to 1.1 (the first launch offers to remove the local CA installed by 1.0) |

### Reporting a vulnerability

Please do not open a public issue for security problems. Use **Security → Report a vulnerability** on this repository (GitHub private vulnerability reporting). Include the version (Help → About), steps to reproduce and the impact you expect.

### Security model

W.S.T is a **single-user tool that runs on one Windows PC**.

- The relay server listens only on loopback (`127.0.0.1`, `::1`). Remote access from other PCs is not supported (removed in 1.1).
- Every start creates an access token. HTTP and WebSocket requests are rejected unless the Host header is `127.0.0.1`, `localhost` or `[::1]` with the real port (DNS rebinding protection), and WebSocket Origin must match.
- SSH host keys use trust on first use. A changed key is refused until you replace it explicitly.
- Saved passwords are optional and protected with Windows DPAPI for the current Windows account, optionally with a master password (scrypt + AES-GCM).
- Anyone who can run code as your Windows account can use W.S.T the same way you can. Protect the account itself.

### Known issues

These are tracked and not yet fixed:

- The HTTP file server (Tools) follows symbolic links and junctions inside the shared folder, so files outside the folder can be served if such links exist.
- A TFTP upload is kept in memory until it finishes and has no size limit. Upload (write) is off by default.
- SFTP drag-out downloads are loaded fully into memory (up to 512 MB per file).
- No Content-Security-Policy header yet.

The file servers listen on `127.0.0.1` by default. If you choose another address, the shared folder is open to your network without authentication.

## 한국어

### 지원 버전

보안 수정은 최신 릴리즈에만 합니다.

| 버전 | 지원 |
|---|---|
| 1.1.x | 지원 |
| 1.0.x | 미지원. 1.1로 올리세요(처음 실행할 때 1.0이 설치한 로컬 CA 제거를 안내합니다) |

### 취약점 제보

보안 문제는 공개 이슈로 올리지 말고, 이 저장소의 **Security → Report a vulnerability**(GitHub 비공개 취약점 제보)를 이용해 주세요. 버전(도움말 → 버전 정보), 재현 방법, 예상되는 영향을 적어 주시면 됩니다.

### 보안 모델

W.S.T는 **Windows PC 한 대에서 한 사람이 쓰는 도구**입니다.

- 중계 서버는 루프백(`127.0.0.1`, `::1`)에서만 열립니다. 다른 PC에서 접속하는 기능은 없습니다(1.1에서 제거).
- 실행할 때마다 접속 토큰을 만듭니다. Host 헤더가 `127.0.0.1`·`localhost`·`[::1]`과 실제 포트가 아니면 HTTP·WebSocket 요청을 거부하고(DNS 리바인딩 방어), WebSocket Origin도 일치해야 합니다.
- SSH 호스트 키는 처음 접속할 때 확인합니다(TOFU). 키가 바뀌면 직접 교체하기 전까지 접속을 거부합니다.
- 비밀번호 저장은 선택 사항이며, 현재 Windows 계정의 DPAPI로 보호합니다. 마스터 비밀번호를 설정하면 scrypt와 AES-GCM 보호가 더해집니다.
- 내 Windows 계정으로 코드를 실행할 수 있는 사람은 W.S.T도 나와 똑같이 쓸 수 있습니다. 계정 자체를 보호하세요.

### 알려진 문제

추적 중이며 아직 고치지 않았습니다.

- 도구의 HTTP 파일 서버는 공유 폴더 안의 심볼릭 링크·정션을 따라가므로, 그런 링크가 있으면 폴더 밖 파일이 제공될 수 있습니다.
- TFTP 업로드는 끝날 때까지 메모리에 쌓이고 크기 제한이 없습니다. 업로드(쓰기)는 기본으로 꺼져 있습니다.
- SFTP 끌어 내려받기는 파일 전체를 메모리에 올립니다(파일당 최대 512MB).
- Content-Security-Policy 헤더가 아직 없습니다.

파일 서버는 기본으로 `127.0.0.1`에 열립니다. 다른 주소를 고르면 공유 폴더가 인증 없이 네트워크에 열립니다.
