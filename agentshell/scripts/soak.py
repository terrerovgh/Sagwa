"""Supervised CoreS3/gateway soak, using telemetry only (USB resets the board)."""
import argparse,datetime,fcntl,json,os,statistics,time
from pathlib import Path
from admin import request

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--hours',type=float,default=24);parser.add_argument('--interval',type=float,default=30);parser.add_argument('--output',type=Path,default=root/'evidence/soak.json');args=parser.parse_args()
if args.hours<=0 or args.interval<5:raise SystemExit('Invalid sampling duration')
args.output.parent.mkdir(exist_ok=True,parents=True)
log=args.output.with_suffix('.ndjson');lock=open(str(args.output)+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
rows=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
started=rows[0]['at'] if rows else time.time()
def slope(points):
    if len(points)<2:return 0
    xs=[(at-points[0][0])/3600 for at,_ in points];ys=[value for _,value in points];x=statistics.mean(xs);y=statistics.mean(ys)
    denominator=sum((v-x)**2 for v in xs)
    return sum((a-x)*(b-y) for a,b in zip(xs,ys))/denominator if denominator else 0
def summary():
    restarts={};prior={};points={};gaps=0;stale=0;errors=0
    for row in rows:
        if row.get('error'):errors+=1;continue
        if row.get('device_age_s',999)>45:stale+=1;continue
        if prior.get('_at') and row['at']-prior['_at']>120:gaps+=1
        prior['_at']=row['at']
        series={'core':row['core'],**row['nodes']}
        for node,value in series.items():
            uptime=value['uptime_s']
            if node in prior and uptime<prior[node]-5:restarts[node]=restarts.get(node,0)+1
            prior[node]=uptime
            if row['at']-started>=600:
                points.setdefault(node,[]).append((row['at'],value['free_heap_bytes'] if node=='core' else value['memory_bytes']))
    memory={}
    for node,values in points.items():
        gradient=slope(values);first=statistics.median(v for _,v in values[:60]);last=statistics.median(v for _,v in values[-60:])
        sustained=(last-first < -512*1024 and gradient < -128*1024) if node=='core' else (last-first>64*1024*1024 and gradient>2*1024*1024)
        memory[node]={'samples':len(values),'first_window_median_bytes':first,'last_window_median_bytes':last,'slope_bytes_per_hour':round(gradient),'sustained_growth_detected':sustained}
    elapsed=time.time()-started;finished=elapsed>=args.hours*3600
    failed=bool(restarts or gaps or stale or errors or any(v['sustained_growth_detected'] for v in memory.values()))
    return {'scope':'CoreS3 and three Node gateways; idle telemetry and ordinary user activity','started_at':datetime.datetime.fromtimestamp(started,datetime.timezone.utc).isoformat(),'duration_required_s':args.hours*3600,'elapsed_s':round(elapsed),'samples':len(rows),'status':('failed' if failed else 'passed') if finished else 'running','restarts':restarts,'sample_gaps_over_120s':gaps,'stale_device_samples':stale,'request_errors':errors,'memory':memory,'thresholds':{'warmup_s':600,'core_heap_loss_bytes':512*1024,'core_heap_loss_bytes_per_hour':128*1024,'gateway_rss_growth_bytes':64*1024*1024,'gateway_rss_growth_bytes_per_hour':2*1024*1024},'limitations':['Not a voice/camera stress test. Voice processes are validated separately.','Memory thresholds flag trends; inspect the samples before accepting.']}
while True:
    if rows and time.time()-started>=args.hours*3600:break
    at=time.time()
    try:
        devices=request('/v1/devices');nodes=request('/v1/nodes');device=devices['devices/telemetry/device:cores3-80456b4d5f7c']
        received=datetime.datetime.fromisoformat(device['received_at'].replace('Z','+00:00')).timestamp()
        row={'at':at,'device_age_s':round(at-received,2),'firmware':device['capabilities']['firmware'],'gateway':device['gateway'],'core':device['readings']['runtime'],'nodes':{node['node']:{'uptime_s':node['uptime_s'],'memory_bytes':node['memory_bytes'],'age_s':round(at-datetime.datetime.fromisoformat(node['received_at'].replace('Z','+00:00')).timestamp(),2)} for node in nodes}}
        if set(row['nodes'])!={'mac-mini','tuf-infra','lenlab'} or any(node['age_s']>20 for node in row['nodes'].values()):raise RuntimeError('node_telemetry_stale')
    except Exception as error:row={'at':at,'error':type(error).__name__}
    with open(log,'a') as stream:stream.write(json.dumps(row,separators=(',',':'))+'\n');stream.flush();os.fsync(stream.fileno())
    rows.append(row);temporary=args.output.with_suffix('.tmp');temporary.write_text(json.dumps(summary(),indent=2)+'\n');os.replace(temporary,args.output)
    time.sleep(max(1,args.interval-(time.time()-at)))
args.output.write_text(json.dumps(summary(),indent=2)+'\n')
