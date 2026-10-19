"""Recreate only checked-in, conspicuously synthetic example inputs."""
import csv,json
from pathlib import Path
ROOT=Path(__file__).parent

def main():
    rows=[]; texts=[]
    for i in range(18):
        n=(2,5,7)[i%3]; split=('development','validation','test')[i//6]
        candidates=[dict(candidate_id='device-'+str(j+1),candidate_name='Synthetic speaker '+str(j+1),price=10+j*2+i%5,
                         advertised=j==i%n,battery_hours=4+j) for j in range(n)]
        rows.append(dict(case_id='speaker-'+str(i),group_id='synthetic-customer-'+str(i),split=split,
                         outcome=candidates[i%n]['candidate_id'],candidates=candidates,context='For a small room',
                         history=[dict(observation_id='past-speaker-'+str(i),value={'choice':candidates[0]['candidate_id']})]))
        texts.append(dict(case_id='review-'+str(i),group_id='synthetic-author-'+str(i),split=split,
                          text='Great sound, love it' if i%2 else 'Broken controls, poor sound',outcome='positive' if i%2 else 'negative'))
    for name,data in [('products.jsonl',rows),('text.jsonl',texts)]:
        (ROOT/name).write_text(''.join(json.dumps(r)+'\n' for r in data))
    with (ROOT/'products.csv').open('w',newline='') as f:
        columns=['case_id','group_id','split','outcome','context','history','candidate_id','candidate_name','price','advertised','battery_hours']
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for row in rows:
            for candidate in row['candidates']:
                base={k:v for k,v in row.items() if k!='candidates'};base['history']=json.dumps(base['history'])
                w.writerow(dict(base,**candidate))

if __name__=='__main__': main()
