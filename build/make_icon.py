"""앱 아이콘 생성: build/webssh.ico(exe용), static/favicon.ico(크롬 앱 창·작업표시줄용). 빌드 때 1회 (Pillow 필요)."""
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
S = 1024

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((32, 32, S - 32, S - 32), radius=190, fill="#10233f")
d.rounded_rectangle((32, 32, S - 32, S - 32), radius=190, outline="#3b82f6", width=44)
d.line([(250, 310), (510, 512), (250, 714)], fill="#ffffff", width=112, joint="curve")   # 프롬프트 >
d.rectangle((560, 660, 790, 762), fill="#56d364")                                        # 커서 _

sizes = [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]
for path in (BASE / "build" / "webssh.ico", BASE / "static" / "favicon.ico"):
    img.save(path, sizes=sizes)
