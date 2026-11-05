"""exe 빌드: python build/build_exe.py → 프로젝트 루트에 'W.S.T.exe' + _internal/ 생성.

onedir 방식: onefile은 실행마다 임시 폴더에 풀어서 시작이 느리고 백신 오탐이 잦다.
static/·data/·certs/·logs/는 exe에 넣지 않고 옆 폴더를 그대로 쓴다.
파이썬 코드를 고치면 다시 빌드, static/만 고치면 빌드 불필요.
필요 패키지: pyinstaller, pillow + 실행(콘솔).bat의 패키지. 빌드 전 앱을 종료할 것.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
NAME = "W.S.T"
WORK = BASE / "build"


def bump_build():
    """빌드 번호 = version_info.txt filevers/prodvers 넷째 자리. 빌드할 때마다 1 올림 (도움말 → 버전 정보에 build(N))."""
    p = WORK / "version_info.txt"
    text = p.read_text(encoding="utf-8")
    n = int(re.search(r"filevers=\(\d+, \d+, \d+, (\d+)\)", text).group(1)) + 1
    text = re.sub(r"(filevers|prodvers)=\((\d+), (\d+), (\d+), \d+\)", lambda m: f"{m[1]}=({m[2]}, {m[3]}, {m[4]}, {n})", text)
    p.write_text(text, encoding="utf-8", newline="")
    return n


def main():
    print(f"build({bump_build()})")
    if not (WORK / "webssh.ico").exists():
        subprocess.run([sys.executable, str(WORK / "make_icon.py")], check=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                    "--name", NAME, "--icon", str(WORK / "webssh.ico"),
                    "--version-file", str(WORK / "version_info.txt"),
                    "--add-data", f"{WORK / 'version_info.txt'};.",
                    "--collect-all", "winpty", "--hidden-import", "tkinter.filedialog",
                    "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "work"), "--specpath", str(WORK),
                    str(BASE / "server.py")], cwd=BASE, check=True)
    out = WORK / "dist" / NAME
    shutil.rmtree(BASE / "_internal", ignore_errors=True)
    shutil.move(out / "_internal", BASE / "_internal")
    shutil.move(out / f"{NAME}.exe", BASE / f"{NAME}.exe")
    shutil.rmtree(WORK / "dist")
    shutil.rmtree(WORK / "work")
    (WORK / f"{NAME}.spec").unlink(missing_ok=True)
    print(f"완료: {BASE / (NAME + '.exe')}")


if __name__ == "__main__":
    main()
