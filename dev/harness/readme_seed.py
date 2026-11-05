"""README 촬영용 더미 데이터 생성: python dev/harness/readme_seed.py <데이터 폴더>.

실제 data/는 거부하며 기존 sessions.json/settings.json은 덮어쓰지 않는다.
실행 순서는 dev/README.md와 readme_shots.js 맨 위 주석 참고.
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", type=Path)
    args = ap.parse_args()
    dest = args.data.resolve()
    actual = Path(__file__).resolve().parents[2] / "data"
    if dest == actual or actual in dest.parents:
        ap.error("실제 data/ 대신 별도의 시험 폴더를 지정하세요")
    for name in ("sessions.json", "settings.json"):
        if (dest / name).exists():
            ap.error(f"기존 파일을 덮어쓰지 않습니다: {dest / name}")

    sessions = []
    for name, folder, host in (
        ("web-01", "Web", "127.0.0.1"),
        ("web-02", "Web", "127.0.0.1"),
        ("db-01", "Infrastructure", "192.0.2.21"),
        ("bastion", "Infrastructure", "198.51.100.10"),
        ("cache-01", "Infrastructure", "203.0.113.31"),
    ):
        sessions.append({
            "id": "readme-" + name, "type": "ssh", "name": name,
            "folder": folder, "host": host,
            "port": 2222 if host == "127.0.0.1" else 22,
            "username": "test", "auth": "password", "encoding": "utf-8",
            "log": False, "reconnect": False,
        })
    data = {"folders": ["Web", "Infrastructure"], "sessions": sessions, "tunnels": [
        {"id": "readme-http", "name": "web-preview", "type": "local",
         "via": "readme-web-01", "listenPort": 18080,
         "destHost": "192.0.2.11", "destPort": 8080, "autoStart": False},
        {"id": "readme-socks", "name": "dev-proxy", "type": "dynamic",
         "via": "readme-web-02", "listenPort": 18081,
         "destHost": "127.0.0.1", "destPort": 0, "autoStart": False},
    ]}
    settings = {"logDefault": False, "logDir": str(dest / "demo_logs"),
                "monitor": True, "followFolder": False, "globalHotkey": False,
                "sharedPath": "", "hiddenFeatures": []}
    dest.mkdir(parents=True, exist_ok=True)
    # 가짜 SFTP의 /home/test 경로. 앱 데이터나 실제 홈 폴더를 노출하지 않는다.
    home = dest / "sftp_root" / "home" / "test"
    for folder in ("app", "backups", "reports"):
        (home / folder).mkdir(parents=True, exist_ok=True)
    for name, body in {
        "README.txt": "Demo workspace for README screenshots.\n",
        "deploy.sh": "#!/bin/sh\necho 'demo deployment complete'\n",
        "app.conf": "listen=8080\nserver_name=web-01\n",
        "reports/health.txt": "web-01 ok\nweb-02 ok\n",
    }.items():
        p = home / name
        if not p.exists():
            p.write_text(body, encoding="utf-8")
    for name, obj in (("sessions", data), ("settings", settings)):
        (dest / f"{name}.json").write_text(
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created {dest}: 2 folders, 5 sessions, 2 tunnels; SFTP root: {dest / 'sftp_root'}")


if __name__ == "__main__":
    main()
