DB.sessions.push({id:'s-prod', type:'ssh', name:'운영 웹서버', folder:'고객사/A', host:'127.0.0.1', port:2222, username:'test', auth:'password', color:'red', encoding:'utf-8'});
DB.sessions.push({id:'s-dev', type:'ssh', name:'개발 서버', folder:'고객사/A', host:'127.0.0.1', port:2222, username:'test', auth:'password', color:'green', encoding:'utf-8'});
openFolders.add('고객사'); openFolders.add('고객사/A'); renderTree();
autoAnswer();
openSpec(findSession('s-prod')); await until(() => tabs[0]?.state === 'on', 10000);
openSpec(findSession('s-dev')); await until(() => tabs[1]?.state === 'on', 10000);
typeIn(tabs[1], 'echo error: disk failed ok done 10.0.0.5\r');
setLayout('2v'); await W(800);
// SHOT split
openFind(tabs[1]); const q = tabs[1].pane.querySelector('.fq'); q.value='error'; q.dispatchEvent(new Event('input')); await W(300);
// SHOT find
closeFind(tabs[1]); toggleMultiExec(true); await W(400);
// SHOT multi
toggleMultiExec(false); openPalette('개발'); await W(300);
// SHOT palette
$('#paletteDlg').close(); pasteText(tabs[0], 'rm -rf /var/log/old\nsystemctl restart nginx\n'); await W(400);
// SHOT paste
$('#pasteDlg').close(); setSide('sftp'); await W(1500);
