"""Optional headless browser QA using an already installed Chrome/Edge."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[1]
demo = sorted((root / 'evidence').glob('demo-*/replay.html'))[-1]
folder = demo.parent / ('browser-check-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
folder.mkdir()
candidates = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe', Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe']
if '--edge' in sys.argv:
    candidates.reverse()
browser = next((p for p in candidates if p.is_file()), None)
if not browser:
    raise SystemExit('未找到已安装的Chrome或Edge；不自动安装。请手动打开回放检查。')
script = '''<script>
try {
const assert=(condition,message)=>{if(!condition)throw new Error(message)};
const initial=$('title').textContent;
assert(initial==='范围与启动','initial chapter');
$('next').click();assert($('title').textContent==='发现疑似重复消费','next chapter');
$('prev').click();assert($('title').textContent===initial,'previous chapter');
$('play').click();assert(playing&&$('play').textContent==='暂停','play');
$('play').click();assert(!playing,'pause');
$('seek').value=200;$('seek').dispatchEvent(new Event('input'));assert(elapsed===200,'seek');
$('speed').value='10';assert(Number($('speed').value)===10,'speed');
elapsed=duration-0.01;draw();assert($('title').textContent==='验收证据与交付边界','last chapter');
elapsed=5*span+0.1;draw();assert($('title').textContent==='部分到账与差额','partial chapter');
assert($('snapshot').textContent.includes('4000'),'actual partial snapshot');
document.body.dataset.qa='PASS';
const badge=document.createElement('p');badge.id='qa-result';badge.textContent='Browser QA PASS: initial / next / previous / play / pause / seek / speed / final / actual snapshot';document.body.appendChild(badge);
} catch(error) {document.body.dataset.qa='FAIL';const badge=document.createElement('p');badge.id='qa-result';badge.textContent=String(error);document.body.appendChild(badge);}
</script>'''
qa = folder / 'browser-qa.html'
qa.write_text(demo.read_text(encoding='utf-8').replace('</html>', script + '</html>'), encoding='utf-8')
argv = [str(browser), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-background-networking', '--disable-component-update', '--disable-crash-reporter', '--disable-breakpad', '--disable-crashpad-for-testing', '--hide-scrollbars', '--window-size=1440,1080', '--virtual-time-budget=1000', '--user-data-dir=' + str(folder / 'browser-profile'), '--screenshot=' + str(folder / 'preview.png'), '--dump-dom', qa.as_uri()]
if '--compat-local-only' in sys.argv:
    # Only this newly generated, synthetic local page is loaded. This switch
    # addresses headless child-process restrictions; never use on remote pages.
    argv.insert(1, '--no-sandbox')
done = subprocess.run(argv, capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
(folder / 'browser-dom-original.html').write_bytes(done.stdout)
(folder / 'browser-stderr-original.txt').write_bytes(done.stderr)
report = {'argv': argv, 'exit_code': done.returncode, 'dom_assertions_passed': b'data-qa="PASS"' in done.stdout, 'screenshot_exists': (folder / 'preview.png').is_file(), 'scope': '实际安装的浏览器无头渲染，检查章节、播放/暂停/定位/速度/数据展示；不是录屏或7分钟实时时长测量。'}
(folder / 'browser-qa-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report['dom_assertions_passed'] and report['screenshot_exists'] else 1)
