"""Local, read-only acceptance soak. No credentials, external messages or repairs.
Use --hours 8 to sample the existing Compose stack once a minute.
Report lives outside the source tree. Ctrl-C or SIGTERM stops checks only.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT.parent/'yunguo-mvp-overnight-check.json'
STOP=False
QUERY="""
import json
from app.core.db import SessionLocal
from app.services.monitoring import inspect
with SessionLocal() as db:
 data=inspect(db)
 print(json.dumps({'enabled':data['enabled'],'workers':{w['service']:w['status'] for w in data['workers']}}))
"""

def utc():return datetime.now(timezone.utc).isoformat()
def halt(*_):
    global STOP
    STOP=True

def save(data):
    temporary=REPORT.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as file:json.dump(data,file,ensure_ascii=False,indent=2)
    os.replace(temporary,REPORT)

def sample(client, container=False):
    errors=[];workers={}
    try:
        result=client.get('/api/health')
        if result.status_code!=200 or result.json().get('status')!='ok':errors.append('site_health_failed')
    except Exception:errors.append('site_health_unreachable')
    try:
        if container:
            from app.core.db import SessionLocal
            from app.services.monitoring import inspect
            with SessionLocal() as db:
                result=inspect(db)
                data={'enabled':result['enabled'],'workers':{w['service']:w['status'] for w in result['workers']}}
        else:
            result=subprocess.run(['docker','compose','exec','-T','api','python','-c',QUERY],cwd=ROOT,capture_output=True,text=True,timeout=20,check=True)
            data=json.loads(result.stdout)
        workers=data['workers']
        if not data['enabled']:errors.append('monitor_disabled')
        for service,status in workers.items():
            if status not in ('RECENT','NOT_REQUIRED'):errors.append(service+'_heartbeat_'+status.lower())
    except Exception:errors.append('queue_status_unavailable')
    return {'at':utc(),'passed':not errors,'errors':errors,'workers':workers}

def main():
    global REPORT
    parser=argparse.ArgumentParser()
    parser.add_argument('--hours',type=float,default=8)
    parser.add_argument('--interval',type=int,default=60)
    parser.add_argument('--container',action='store_true')
    parser.add_argument('--report',type=Path)
    parser.add_argument('--target',default='http://127.0.0.1:8080')
    args=parser.parse_args()
    if args.report:REPORT=args.report
    if not 0<args.hours<=12 or not 5<=args.interval<=300:parser.error('hours must be (0,12], interval 5..300')
    if REPORT.exists() and not args.container:
        prior=json.loads(REPORT.read_text())
        if prior.get('state')=='running':
            try:os.kill(prior['pid'],0)
            except ProcessLookupError:pass
            else:raise RuntimeError('An overnight check is already running')
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,halt)
    data={'state':'running','mode':'container' if args.container else 'local','pid':os.getpid(),'started_at':utc(),'requested_hours':args.hours,'interval_seconds':args.interval,
        'samples':0,'passed':0,'failed':0,'last_sample':None,'recent_failures':[]}
    deadline=time.monotonic()+args.hours*3600
    with httpx.Client(base_url=args.target,timeout=10) as client:
        while not STOP:
            current=sample(client,args.container)
            data['samples']+=1;data['passed' if current['passed'] else 'failed']+=1
            data['last_sample']=current
            if not current['passed']:data['recent_failures']=(data['recent_failures']+[current])[-100:]
            save(data)
            print(f"Sample {data['samples']}: {'PASS' if current['passed'] else 'FAIL'}",flush=True)
            if time.monotonic()>=deadline:break
            next_sample=min(deadline,time.monotonic()+args.interval)
            while not STOP and time.monotonic()<next_sample:time.sleep(max(0,min(1,next_sample-time.monotonic())))
    data['state']='stopped' if STOP else 'completed';data['finished_at']=utc();save(data)
    print('Local acceptance soak finished; see report for actual sample results',flush=True)

if __name__=='__main__':main()
