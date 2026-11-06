#!/usr/bin/env python3
"""Local headless Chrome QA for both tabs, keyboard behavior and overflow."""
import argparse
import asyncio
import base64
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import urlopen

from tornado.websocket import websocket_connect

ROOT = Path(__file__).resolve().parents[1]
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


async def inspect_browser(browser, temp, source, image, width, qa):
    port_file = temp / 'profile/DevToolsActivePort'
    deadline = time.monotonic() + 20
    while not port_file.exists():
        if browser.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError('Temporary Chrome did not expose its debugging port')
        await asyncio.sleep(.1)
    port = int(port_file.read_text().splitlines()[0])
    with urlopen(f'http://127.0.0.1:{port}/json/list') as stream:
        targets = json.load(stream)
    target = next(t for t in targets if t['type'] == 'page')
    ws = await websocket_connect(target['webSocketDebuggerUrl'], max_message_size=80_000_000)
    counter = 0
    events = []

    async def command(method, params=None):
        nonlocal counter
        counter += 1; request_id = counter
        await ws.write_message(json.dumps({'id': request_id, 'method': method, 'params': params or {}}))
        while True:
            message = json.loads(await ws.read_message())
            if message.get('id') == request_id:
                if 'error' in message: raise RuntimeError(message['error'])
                return message.get('result', {})
            events.append(message)

    await command('Page.enable')
    await command('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1250, 'deviceScaleFactor': 1, 'mobile': False})
    await command('Page.navigate', {'url': source.as_uri()})
    while not any(e.get('method') == 'Page.loadEventFired' for e in events):
        message = json.loads(await ws.read_message()); events.append(message)
    expression = '(async()=>{await document.fonts.ready;' + qa + ';await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return result;})()'
    result = await command('Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
    if result.get('exceptionDetails'): raise RuntimeError(result['exceptionDetails'])
    screenshot = await command('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False, 'fromSurface': True})
    image.write_bytes(base64.b64decode(screenshot['data']))
    ws.close()
    return result['result']['value']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, default=1440)
    parser.add_argument('--tab', choices=('evaluation', 'example'), default='evaluation')
    parser.add_argument('--section', default='')
    args = parser.parse_args()
    qa = r'''
const tabs=[...document.querySelectorAll('[role=tab]')];const checks={};
tabs[0].focus();tabs[0].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
checks.arrowRight= document.activeElement===tabs[1]&&tabs[1].getAttribute('aria-selected')==='true'&&!document.getElementById('example').hidden&&document.getElementById('evaluation').hidden;
tabs[1].dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));checks.home=document.activeElement===tabs[0]&&!document.getElementById('evaluation').hidden;
tabs[0].dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));checks.end=document.activeElement===tabs[1];
tabs[1].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));checks.arrowLeft=document.activeElement===tabs[0];
tabs[TAB_INDEX].click();document.activeElement.blur();
const panel=document.getElementById(TAB_NAME);
const disclosures=[...panel.querySelectorAll('details')];checks.disclosuresStartClosed=disclosures.every(d=>!d.open);
const disclosure=disclosures[0];if(disclosure){const summary=disclosure.querySelector(':scope > summary');summary.click();const opened=disclosure.open;summary.click();checks.disclosureToggle=opened&&!disclosure.open;}else checks.disclosureToggle=true;
const selected=SECTION?document.querySelector(SECTION):null;if(selected){for(let p=selected;p;p=p.parentElement){if(p.tagName==='DETAILS')p.open=true;}scrollTo(0,selected.getBoundingClientRect().top+scrollY-24);}else scrollTo(0,0);
const overflow=[...panel.querySelectorAll('p,h1,h2,h3,h4,.matrix,.two-col,.verbatim,.prompt,.family-tables')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,kind:e.className,right:e.getBoundingClientRect().right,text:e.textContent.slice(0,90)}));
const result={tab:TAB_NAME,width:innerWidth,documentWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,keyboard:checks,tabCount:tabs.length,visiblePanelCount:[...document.querySelectorAll('[role=tabpanel]')].filter(p=>!p.hidden).length,offlineMath:[...panel.querySelectorAll('math')].map(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})),externalResources:performance.getEntriesByType('resource').filter(e=>/^https?:/.test(e.name)).map(e=>e.name),overflow};
document.body.insertAdjacentHTML('beforeend','<pre id="qa-result" hidden>'+JSON.stringify(result).replace(/</g,'&lt;')+'</pre>');
'''.replace('TAB_INDEX', '0' if args.tab == 'evaluation' else '1').replace('TAB_NAME', json.dumps(args.tab)).replace('SECTION', json.dumps(args.section))
    tag = args.tab + ('-' + args.section.removeprefix('#').replace(' ', '-') if args.section else '') + '-' + str(args.width)
    out = ROOT / 'presentation/support/browser-checks'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='choice-two-tab-qa-') as temp:
        temp = Path(temp)
        page = (ROOT / 'presentation/index.html').read_text()
        source = temp / 'presentation.html'
        source.write_text(page)
        image = out / (tag + '.png')
        browser = subprocess.Popen([CHROME, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--user-data-dir=' + str(temp / 'profile'),
            '--window-size=' + str(args.width) + ',1250', '--force-device-scale-factor=1', '--remote-debugging-port=0',
            'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            result = asyncio.run(asyncio.wait_for(inspect_browser(browser, temp, source, image, args.width, qa), timeout=45))
        finally:
            browser.terminate()
            browser.wait(timeout=10)
    assert all(result['keyboard'].values()), result
    assert result['tabCount'] == 2 and result['visiblePanelCount'] == 1
    assert not result['externalResources'] and not result['overflow'], result
    assert result['documentWidth'] <= result['width']
    (out / (tag + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'screenshot': str(image), 'checks': result}, indent=2))


if __name__ == '__main__':
    main()
