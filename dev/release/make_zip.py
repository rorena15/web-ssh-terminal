"""관리 대상만 W.S.T/ 접두로 배포 ZIP에 넣는다."""
import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wst.update import local_hashes


def make_zip(base: Path, output: Path):
    files = local_hashes(base)
    if "W.S.T.exe" not in files:
        raise ValueError("W.S.T.exe 없음")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files):
            z.write(base / p, "W.S.T/" + p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, default=Path.cwd())
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    make_zip(args.base, args.output)
