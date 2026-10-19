"""Independent source/display checks plus concurrent-writer snapshot edge cases."""
import base64
from collections import Counter
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from presentation_snapshot import ROOT, REMOTE, REMOTE_READER, latest


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.text=[]; self.links=[]; self.headings=[]; self.in_h2=False
        self.prompts=[]; self.active_prompt=None; self.in_mark=False; self.marked=[]
        self.mark_positions=[]; self.observed=[]; self.active_observed=None
        self.counterfactuals=0; self.scripts=0
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        assert tag not in ('select','progress','iframe','details'), tag
        if tag=='script':
            assert 'src' not in attrs; self.scripts+=1
        if tag=='h2': self.in_h2=True
        if tag=='a': self.links.append(attrs['href'])
        if tag=='pre' and attrs.get('class')=='prompt-text': self.active_prompt=''
        if tag=='mark' and attrs.get('class')=='prompt-change':
            self.in_mark=True; self.marked.append('')
            self.mark_positions.append((len(self.prompts),len(self.active_prompt)))
        if tag=='p' and attrs.get('class')=='small observed-purchase':self.active_observed=''
        if tag=='article' and attrs.get('class')=='counterfactual':self.counterfactuals+=1
    def handle_endtag(self,tag):
        if tag=='h2': self.in_h2=False
        if tag=='pre' and self.active_prompt is not None:
            self.prompts.append(self.active_prompt);self.active_prompt=None
        if tag=='mark':self.in_mark=False
        if tag=='p' and self.active_observed is not None:
            self.observed.append(self.active_observed);self.active_observed=None
    def handle_data(self,data):
        self.text.append(data)
        if self.in_h2: self.headings.append(data)
        if self.active_prompt is not None:self.active_prompt+=data
        if self.in_mark:self.marked[-1]+=data
        if self.active_observed is not None:self.active_observed+=data


def test_snapshot_reader():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp); out=root/'outputs_resumed_v1';out.mkdir()
        control=root/'execution_resumed_v1';control.mkdir()
        (control/'study_plan.json').write_text('{}')
        for filename in ['interventions.jsonl','explanations.jsonl','predictions.jsonl','cases.jsonl']:
            (out/filename).write_bytes(b'{"complete":true}\n{"unfinished":')
        (out/'run_manifest.json').write_text('{}')
        original={p.name:p.read_bytes() for p in out.iterdir()}
        script=REMOTE_READER.replace(REMOTE,str(root))
        result=subprocess.run([sys.executable,'-B','-'],input=script.encode(),capture_output=True,check=True)
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tar:
            meta=json.loads(tar.extractfile('snapshot_provenance.json').read())
            assert meta['read_order'][:3]==['interventions.jsonl','explanations.jsonl','predictions.jsonl']
            assert tar.extractfile('interventions.jsonl').read()==b'{"complete":true}\n'
            assert meta['files']['interventions.jsonl']['incomplete_tail_bytes']>0
        assert original=={p.name:p.read_bytes() for p in out.iterdir()}, 'Reader mutated source files'
        (out/'interventions.jsonl').write_bytes(b'{"broken":}\n')
        failed=subprocess.run([sys.executable,'-B','-'],input=script.encode(),capture_output=True)
        assert failed.returncode!=0, 'Malformed complete records must fail'


def verify_display(snapshot=None, page_path=None):
    snapshot=snapshot or latest(); f=json.loads((snapshot/'presentation_findings.json').read_text())
    rows=lambda filename:[json.loads(line) for line in (snapshot/filename).read_text().splitlines()]
    cases={c['case_id']:c for c in rows('cases.jsonl')}
    predictions=rows('predictions.jsonl'); explanations=rows('explanations.jsonl'); interventions=rows('interventions.jsonl')
    page=Page();page.feed((page_path or ROOT/'presentation/index.html').read_text());text=' '.join(page.text)
    assert page.headings==['What was studied','What the model saw','Prediction findings','What the explanations said','What changed during counterfactual tests','What we learned and what remains uncertain']
    counts=Counter(c['outcome'] for c in cases.values() if c['split']=='development')
    fixed=sorted(counts, key=lambda cid:(-counts[cid],cid))[0]
    for split in ('development','validation','test'):
        for cond in ('no_history','with_history'):
            ps=[p for p in predictions if p['split']==split and p['condition']==cond]
            correct=sum(p['prediction']==cases[p['case_id']]['outcome'] for p in ps)
            assert f"{correct:,} correct out of {len(ps):,} evaluated purchases." in text
            assert f"{correct/len(ps)*100:.1f}%" in text
            expected=sum(p['outcome']==fixed for p in ps)
            assert f['prediction'][split][cond]['fixed_correct']==expected
            support_hits=0
            for p in ps:
                c=cases[p['case_id']]
                support=Counter(e['value']['choice'] for e in c['evidence'] if e['type']=='history')
                choice=sorted([x['id'] for x in c['candidates']],key=lambda cid:(-support[cid],cid))[0]
                support_hits+=choice==c['outcome']
            assert f['prediction'][split][cond]['support_correct']==support_hits
            if split!='development':
                measured=[i for i in interventions if i['split']==split and i['condition']==cond and i['status']=='measured']
                removed=[i for i in measured if i['spec']['kind']=='cited_remove']
                changed=sum(i['before']['prediction']!=i['after']['prediction'] for i in removed)
                if removed: assert f'{changed} of {len(removed)} purchases' in text
                reordered=[i for i in measured if i['spec']['kind']=='presentation']
                changed=sum(i['before']['prediction']!=i['after']['prediction'] for i in reordered)
                if reordered: assert f'{changed} of {len(reordered)} reorderings' in text
    by_id={e['record_id']:e for e in explanations};downloads=0
    for link in page.links:
        if link.startswith('data:'):
            decoded=json.loads(base64.b64decode(link.split(',',1)[1]));e=by_id[decoded['record_id']]
            assert decoded['raw']==e['raw'] and decoded['prompt']==e['prompt'];downloads+=1
        else:
            assert '://' not in link and (ROOT/'presentation'/link).is_file(),link
    assert downloads==2*len(f['examples'])
    pm={p['record_id']:p for p in predictions};im={i['record_id']:i for i in interventions}
    expected=[]
    first=f['examples'][0]
    for cond in ('no_history','with_history'):
        expected.append(pm[by_id[first['explanation_ids'][cond]]['prediction_id']]['prompt'])
    for example in f['examples']:
        for cond in ('no_history','with_history'):
            e=by_id[example['explanation_ids'][cond]]
            expected.extend([pm[e['prediction_id']]['prompt'],e['prompt']])
    cf=[im[rid] for rid in f['illustrative_intervention_ids']]
    assert [s['category'] for s in f['counterfactual_examples']]==['cited','uncited','price','order']
    assert [s['title'] for s in f['counterfactual_examples']]==['Remove or mask cited evidence','Remove comparable uncited evidence','Change a price','Change presentation order']
    after_indices=[]
    for i in cf:
        assert i['status']=='measured'
        after_indices.append(len(expected)+1)
        expected.extend([i['before']['prompt'],i['after']['prompt']])
    assert page.prompts==expected, 'Displayed inputs differ from exact saved prompts'
    assert page.counterfactuals==4 and page.scripts==1
    assert len(page.marked)>=4
    for block,(index,offset) in zip(page.marked,page.mark_positions):
        assert index in after_indices
        assert expected[index][offset:offset+len(block)]==block
        assert expected[index-1][offset:offset+len(block)]!=block, 'Highlighted text was neither changed nor moved'
    assert len(page.observed)==4
    for paragraph,i in zip(page.observed,cf):
        case=cases[i['case_id']]
        product=next(c['name'].capitalize() for c in case['candidates'] if c['id']==case['outcome'])
        assert paragraph==f'Observed purchase in the original data: {product} (hidden from the model). The edited scenario has no observed customer purchase.'
    # Independently verify the uncited comparison from actual masks, not the
    # operation's name: keeping cited facts can remove an uncited complement.
    selection=f['counterfactual_examples'][1];uncited=im[selection['record_id']];cited=im[selection['comparator_id']]
    assert uncited['prediction_id']==cited['prediction_id'] and uncited['explanation_id']==cited['explanation_id']
    case=cases[uncited['case_id']]
    available={e['id']:e for e in case['evidence'] if uncited['condition']!='no_history' or e['type']!='history'}
    references=set(by_id[uncited['explanation_id']]['parsed']['evidence_ids'])
    masked=lambda r:{e['id'] for e in r['edited_evidence'] if e.get('masked') and e['id'] in available}
    assert masked(uncited)==set(selection['removed_evidence_ids'])
    assert masked(uncited) and masked(uncited).isdisjoint(references)
    assert masked(cited)==references
    assert Counter(available[eid]['type'] for eid in masked(uncited))==Counter(available[eid]['type'] for eid in masked(cited))
    assert all(label not in text for label in ('A real development purchase','Development example ·','Validation example ·','Test example ·'))
    assert 'From customer evidence to behavioral tests' in text
    assert not any(word in text.lower() for word in ['pending','queue_state','timestamp','progress indicator'])
    return dict(independent_accuracy_and_baselines='passed', measured_denominators='passed',
                embedded_original_responses=downloads, local_supporting_links='passed',
                visible_exact_prompts=len(page.prompts), counterfactual_examples='four requested categories',
                observed_purchases='matched original dataset; no edited customer outcome asserted',
                uncited_comparison='actual masked IDs disjoint from citations; same source case and matching counts/types',
                highlighted_input_changes='matched saved before/after records',
                partial_record_and_malformed_record_checks='passed')


if __name__=='__main__':
    test_snapshot_reader()
    result=verify_display()
    (latest()/'independent_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
