// lib.js 뒤에 붙여 실행. 다른 탭이 없는 시험 페이지에서 시작한다.
const checkSide = (name) => {
  const actual = document.querySelector('#vtabs .on')?.dataset.side;
  if (actual !== name) throw new Error(`sidebar: expected ${name}, got ${actual}`);
};
if (tabs.length) throw new Error('start with no tabs');
setLayout('1');
setSide('sessions');
const first = await openFake();
checkSide('sftp');
closeTab(first, true);
checkSide('sessions');
const second = await openFake();
checkSide('sftp');
const third = await openFake();
checkSide('sftp');
closeTab(third, true);
checkSide('sftp');
if (focused() !== second) throw new Error('remaining tab not focused');
closeTab(second, true);
checkSide('sessions');
return { pass: true };
