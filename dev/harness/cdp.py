"""헤드리스 크롬 CDP 도우미: Page(url) → .js(expr) 로 평가, await 지원.
사용: python cdp.py <url> <script.js|-> : 스크립트(async 함수 본문)를 실행하고 반환값(JSON)을 출력"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class Page:
    def __init__(self, url, port=9333):
        self.url, self.port, self.n = url, port, 0
        self.prof = tempfile.mkdtemp(prefix="cdp")
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}",
                                      f"--user-data-dir={self.prof}", "--window-size=1400,900", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.logs = []

    async def start(self):
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
                ws = [t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"]
                break
            except Exception:
                await asyncio.sleep(0.2)
        self.ws = await websockets.connect(ws, max_size=1 << 26)
        self.pending = {}
        asyncio.create_task(self._reader())
        await self.cmd("Runtime.enable")
        await self.cmd("Page.enable")
        await self.cmd("Browser.grantPermissions", origin=self.url.split("/?")[0].rstrip("/"),
                       permissions=["clipboardReadWrite", "clipboardSanitizedWrite"])
        await self.cmd("Page.navigate", url=self.url)
        await asyncio.sleep(1.5)

    async def _reader(self):
        async for m in self.ws:
            m = json.loads(m)
            if "id" in m and m["id"] in self.pending:
                self.pending.pop(m["id"]).set_result(m)
            elif m.get("method") == "Runtime.consoleAPICalled":
                self.logs.append(" ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"]))
            elif m.get("method") == "Runtime.exceptionThrown":
                self.logs.append("EXC " + json.dumps(m["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:400])
            elif m.get("method") == "Page.javascriptDialogOpening":
                asyncio.create_task(self.cmd("Page.handleJavaScriptDialog", accept=True))

    async def cmd(self, method, **params):
        self.n += 1
        f = asyncio.get_running_loop().create_future()
        self.pending[self.n] = f
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        return await f

    async def js(self, body):
        r = await self.cmd("Runtime.evaluate", expression=f"(async()=>{{{body}}})()", awaitPromise=True, returnByValue=True)
        res = r["result"]
        if "exceptionDetails" in res:
            raise RuntimeError(json.dumps(res["exceptionDetails"])[:800])
        return res["result"].get("value")

    async def shot(self, path):
        import base64
        r = await self.cmd("Page.captureScreenshot", format="png")
        open(path, "wb").write(base64.b64decode(r["result"]["data"]))

    def close(self):
        self.proc.kill()


async def run(url, script):
    p = Page(url)
    await p.start()
    try:
        r = await p.js(script)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    finally:
        for l in p.logs:
            print("LOG", l)
        p.close()


if __name__ == "__main__":
    src = sys.stdin.read() if sys.argv[2] == "-" else open(sys.argv[2], encoding="utf-8").read()
    asyncio.run(run(sys.argv[1], src))
