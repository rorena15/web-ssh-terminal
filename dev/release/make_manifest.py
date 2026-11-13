"""배포 ZIP의 로컬 헤더에서 압축 데이터 오프셋을 계산한다."""
import argparse
import datetime
import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wst.update import REPO, check_path, parse_version


def make_manifest(archive: Path, version_file: Path, tag: str):
    text = version_file.read_text(encoding="utf-8")
    version = re.search(r"'FileVersion',\s*'([^']+)'", text).group(1)
    build = int(re.search(r"filevers=\(\d+, \d+, \d+, (\d+)\)", text).group(1))
    parse_version(version)
    if tag != "v" + version or archive.name != f"W.S.T-v{version}-win64.zip":
        raise ValueError("태그/ZIP 이름과 FileVersion 불일치")
    files, seen = [], set()
    with zipfile.ZipFile(archive) as z, archive.open("rb") as stream:
        for info in z.infolist():
            if not info.filename.startswith("W.S.T/") or info.is_dir():
                raise ValueError("잘못된 ZIP 항목")
            p = info.filename[len("W.S.T/"):]
            check_path(p)
            if p.casefold() in seen or info.compress_type not in (0, 8):
                raise ValueError("중복 경로 또는 압축 형식")
            seen.add(p.casefold())
            stream.seek(info.header_offset)
            header = stream.read(30)
            if header[:4] != b"PK\x03\x04":
                raise ValueError("잘못된 로컬 헤더")
            name_len, extra_len = struct.unpack_from("<HH", header, 26)
            with z.open(info) as content:
                digest = hashlib.file_digest(content, "sha256").hexdigest()
            files.append({"path": p, "size": info.file_size, "sha256": digest,
                          "data_offset": info.header_offset + 30 + name_len + extra_len,
                          "compress_size": info.compress_size, "method": info.compress_type})
    if "w.s.t.exe" not in seen or sum(f["size"] for f in files) > 1 << 30:
        raise ValueError("exe 누락 또는 크기 초과")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"format": 1, "version": version, "build": build,
            "published": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "zip": {"name": archive.name, "size": archive.stat().st_size, "sha256": digest},
            "files": files, "notes_url": f"https://github.com/{REPO}/releases/tag/{tag}"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--version-file", type=Path, default=Path("build/version_info.txt"))
    ap.add_argument("--tag", required=True)
    ap.add_argument("--output", type=Path, default=Path("manifest.json"))
    args = ap.parse_args()
    manifest = make_manifest(args.zip, args.version_file, args.tag)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
