"""Create an offline browser harness; Chrome --dump-dom executes the assertions.

Usage: python tests/browser_smoke.py REPORT /tmp/report-check.html
Then open the generated file headlessly or normally; #browser-test-result reports
PASS/FAIL. The harness changes neither the original report nor any run records.
"""
import json
import re
import sys
from pathlib import Path

source=Path(sys.argv[1]).read_text()
match=re.search(r'(<script id="run-data" type="application/json">)(.*?)(</script>)',source,re.S)
data=json.loads(match.group(2))
# An adversarial model response must remain text, never become a DOM element.
if data['explanations']:
    data['explanations'][0]['raw']['text']='</script><img id="injected-attack" src=x onerror="window.pwned=true">'
    if data['explanations'][0].get('parsed'):
        data['explanations'][0]['parsed']['explanation']=data['explanations'][0]['raw']['text']
payload=json.dumps(data).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
source=source[:match.start(2)]+payload+source[match.end(2):]
harness=r'''
<script>
const failures=[],checks=[];
function check(name,test){try{if(!test())throw new Error('assertion false');checks.push(name);}catch(e){failures.push(name+': '+e.message);}}
function event(id,name='change'){document.getElementById(id).dispatchEvent(new Event(name,{bubbles:true}));}
check('dashboard initialized',()=>!!window.choiceDashboard);
check('no injected DOM or script',()=>!document.getElementById('injected-attack')&&!window.pwned);
check('findings visible initially',()=>!document.getElementById('findings').hidden);
document.querySelector('[data-tab="explorer"]').click();
check('case tab switches',()=>!document.getElementById('explorer').hidden&&document.getElementById('findings').hidden);
document.getElementById('search').value='NO_SUCH_CASE_123456';event('search','input');
check('empty search state',()=>document.getElementById('caseSelect').options.length===0&&document.getElementById('caseDetail').textContent.includes('No cases match'));
document.getElementById('search').value='';event('search','input');
check('search restores cases',()=>document.getElementById('caseSelect').options.length>0);
document.getElementById('correctFilter').value='incorrect';event('correctFilter');
check('correctness filter',()=>window.choiceDashboard.filteredPredictions().every(p=>p.correct===false));
document.getElementById('correctFilter').value='all';event('correctFilter');
document.getElementById('confidenceFilter').value='0.95';event('confidenceFilter','input');
check('confidence filter',()=>window.choiceDashboard.filteredPredictions().every(p=>p.scores&&Math.max(...Object.values(p.scores))>=.95));
document.getElementById('confidenceFilter').value='0';event('confidenceFilter','input');
document.querySelector('[data-tab="lab"]').click();
check('counterfactual tab switches',()=>!document.getElementById('lab').hidden);
const kind=document.getElementById('labType');if([...kind.options].some(o=>o.value==='presentation'))kind.value='presentation';event('labType');
check('intervention filter refreshes measurement',()=>document.getElementById('labMeasurement').options.length===0||document.getElementById('labDetail').textContent.includes(kind.value));
const bundle=JSON.parse(document.getElementById('run-data').textContent);
const measured=bundle.interventions.find(i=>i.after&&bundle.cases.find(c=>c.case_id===i.case_id).candidates.length===7)||bundle.interventions.find(i=>i.status==='measured');
if(measured){
 document.getElementById('labCase').value=measured.prediction_id;event('labCase');
 document.getElementById('labType').value=measured.spec.kind;event('labType');
 document.getElementById('labMeasurement').value=measured.record_id;event('labMeasurement');
 check('selects exact saved measurement',()=>document.getElementById('labDetail').textContent.includes('Reference candidate: '+measured.reference_candidate));
 if(measured.after){const count=bundle.cases.find(c=>c.case_id===measured.case_id).candidates.length;
  check('all before and after candidate scores shown',()=>document.querySelectorAll('#labDetail .barrow').length===2*count);
  check('edited saved prediction shown',()=>document.getElementById('labDetail').textContent.includes('Edited prediction: '+measured.after.prediction));
 }else check('legacy missing scores labelled',()=>document.getElementById('labDetail').textContent.includes('Numerical scores were not recorded'));
}
check('no fabricated sliders',()=>document.querySelectorAll('input[type="range"]').length===0);
document.querySelector('[data-tab="methods"]').click();
check('methods includes provenance',()=>!document.getElementById('methods').hidden&&document.getElementById('methodsDetail').textContent.includes('protocol_version'));
check('external resources absent',()=>document.querySelectorAll('script[src],link[href],iframe').length===0);
document.querySelector('[data-tab="findings"]').click();
check('layout fits viewport',()=>document.documentElement.scrollWidth<=window.innerWidth);
const result=document.createElement('pre');result.id='browser-test-result';result.textContent=JSON.stringify({status:failures.length?'FAIL':'PASS',checks,failures,viewport:{width:innerWidth,documentWidth:document.documentElement.scrollWidth}});document.body.append(result);
</script>'''
Path(sys.argv[2]).write_text(source.replace('</body>',harness+'</body>'))
