"""스크린샷: python shot.py <url> <out_prefix> <script.js>  — 스크립트가 반환한 뒤 화면 캡처, 스크립트가 'SHOT:name'을 console.log하면 그때마다 캡처"""
import asyncio
import sys

from cdp import Page


async def main(url, out, script):
    p = Page(url)
    await p.start()
    try:
        # Chrome 창 크기와 콘텐츠 영역 크기는 다르므로 캡처 영역을 고정한다.
        await p.cmd("Emulation.setDeviceMetricsOverride", width=1400, height=900,
                    deviceScaleFactor=1, mobile=False)
        body = open(script, encoding="utf-8").read()
        lib = open(__file__.replace("shot.py", "lib.js"), encoding="utf-8").read()
        # 스크립트를 단계별로: '// SHOT name' 줄에서 나눠 실행하고 그때마다 캡처
        parts = body.split("// SHOT ")
        await p.js(lib + "window.__lib=1;" + "return 1;")
        for i, part in enumerate(parts):
            if i == 0:
                code = part
                name = None
            else:
                name, _, code = part.partition("\n")
                await p.shot(f"{out}_{name.strip()}.png")
            if code.strip():
                await p.js(lib + code)
        await asyncio.sleep(0.3)
        await p.shot(f"{out}_final.png")
    finally:
        for l in p.logs:
            print("LOG", l)
        p.close()


asyncio.run(main(*sys.argv[1:4]))
