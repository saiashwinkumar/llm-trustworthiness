"""Local-only headless Chrome readability check, in a separate browser profile."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--width',type=int,default=1440);parser.add_argument('--height',type=int,default=6600);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='choice-report-render-') as temp:
        temp=Path(temp)
        page=(ROOT/'presentation/index.html').read_text()
        probe="""<script>const qa={viewport:innerWidth,bodyWidth:document.body.getBoundingClientRect().width,pageWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,overflow:[...document.querySelectorAll('p,h1,h2,h3,.metric,.workflow,.prompt-text')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>({tag:e.tagName,right:e.getBoundingClientRect().right,text:e.textContent.slice(0,50)})),sections:[...document.querySelectorAll('.workflow,.saved-inputs,.example,.counterfactual')].map(e=>({kind:e.className,top:e.getBoundingClientRect().top,height:e.getBoundingClientRect().height})),editedInputs:[...document.querySelectorAll('.counterfactual .prompt-text')].map(e=>({scrollTop:e.scrollTop,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight}))};document.body.insertAdjacentHTML('beforeend','<pre id="qa-result" hidden>'+JSON.stringify(qa)+'</pre>');</script>"""
        source=temp/'preview.html';source.write_text(page.replace('</body>',probe+'</body>'))
        output=ROOT/'presentation/support'/f'preview-{args.width}.png'
        result=subprocess.run([CHROME,'--headless','--disable-gpu','--no-first-run','--no-default-browser-check',
            '--user-data-dir='+str(temp/'profile'),'--window-size='+str(args.width)+','+str(args.height),
            '--hide-scrollbars','--screenshot='+str(output),'--dump-dom',source.as_uri()],capture_output=True,text=True,check=True)
        class Extract(HTMLParser):
            active=False;value=''
            def handle_starttag(self,tag,attrs):
                if dict(attrs).get('id')=='qa-result':self.active=True
            def handle_endtag(self,tag):
                if tag=='pre':self.active=False
            def handle_data(self,data):
                if self.active:self.value+=data
        parser=Extract();parser.feed(result.stdout);metrics=json.loads(parser.value)
        (ROOT/'presentation/support'/f'layout-{args.width}.json').write_text(json.dumps(metrics,indent=2)+'\n')
        print(json.dumps(metrics,indent=2));print(output)


if __name__=='__main__':main()
