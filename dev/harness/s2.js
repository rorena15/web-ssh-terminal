autoAnswer();
await until(() => DB.sessions.length >= 6, 5000, 'db');
openSpec(findSession('vnc1')); const t = tabs[tabs.length - 1];
await until(() => t.state === 'on', 10000, 'vnc'); await W(1200);
const box = t.pane.querySelector('.vnc'); const cv = box.querySelector('canvas');
console.log('VNCDIM', box.clientWidth, box.clientHeight, cv.width, cv.height, getComputedStyle(box.firstElementChild).height);
await api.call('serverStart', { kind: 'http', root: 'C:/Windows/Web', bind: '127.0.0.1', port: 18099 });
console.log("HTTPON");
// SHOT vnc
await api.call('serverStop', { kind: 'http' }).catch(()=>{});
