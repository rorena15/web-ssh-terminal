"""Claude 검증: T1 프런트(주소창 토큰 제거·sessionStorage·새로고침 후 WS) + T5(악성 id가 select에 HTML로 들어가지 않음)
사용: python verify_sec2_front.py <harness 폴더> <url>"""
import asyncio
import json
import sys

sys.path.insert(0, sys.argv[1])
from cdp import Page  # noqa: E402

URL = sys.argv[2]

T1A = """
return { href: location.href, ss: sessionStorage.getItem('webssh.token') };
"""
T1B = """
const t0 = Date.now();
while (Date.now() - t0 < 8000 && !(window.api && DB && DB.sessions)) await new Promise(r => setTimeout(r, 100));
let ok = false, err = '';
try { const r = await api.call('version', {}); ok = !!(r && r.version !== undefined); } catch (e) { err = String(e); }
return { href: location.href, ss: sessionStorage.getItem('webssh.token'), wsAfterReload: ok, err };
"""
T5 = """
const EVIL = '"><img id=pwn src=x onerror="window.__pwn=1">';
window.__pwn = 0;
const t0 = Date.now();
while (Date.now() - t0 < 8000 && !(DB && DB.sessions)) await new Promise(r => setTimeout(r, 100));
DB.sessions.push({ id: EVIL, type: 'ssh', name: 'evil', host: '192.0.2.9', port: 22, user: 'u', folder: '' });
DB.sessions.push({ id: 'normal1', type: 'ssh', name: 'normal', host: '192.0.2.10', port: 22, user: 'u', folder: '' });
DB.macros = [{ id: EVIL, name: 'm', steps: [] }];
const out = {};
try { editSession(DB.sessions.find(s => s.id === 'normal1')); } catch (e) { out.editErr = String(e); }
await new Promise(r => setTimeout(r, 500));
const opts = [...document.querySelectorAll('option')].filter(o => o.value === EVIL);
out.sessionDlgEvilOptions = opts.length;
out.imgInjected = !!document.getElementById('pwn');
document.querySelectorAll('dialog[open]').forEach(d => d.close());
try { editTunnel(null); } catch (e) { out.tunErr = String(e); }
await new Promise(r => setTimeout(r, 500));
out.tunnelEvilOptions = [...document.querySelectorAll('option')].filter(o => o.value === EVIL).length;
out.imgInjectedAfterTunnel = !!document.getElementById('pwn');
await new Promise(r => setTimeout(r, 300));
out.onerrorRan = window.__pwn === 1;
return out;
"""


async def main():
    p = Page(URL)
    await p.start()
    try:
        a = await p.js(T1A)
        await p.cmd("Page.reload")
        await asyncio.sleep(2.5)
        b = await p.js(T1B)
        c = await p.js(T5)
        print(json.dumps({"T1_before_reload": a, "T1_after_reload": b, "T5": c}, ensure_ascii=False, indent=1))
    finally:
        p.close()


asyncio.run(main())
