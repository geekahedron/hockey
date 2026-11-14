import json, urllib.request, datetime as dt, os, time, sys
H={'User-Agent':'Mozilla/5.0','Origin':'https://hockeychallengehelper.com','Referer':'https://hockeychallengehelper.com/'}
def rng(a,b):
    d=dt.date.fromisoformat(a)
    while d<=dt.date.fromisoformat(b): yield d; d+=dt.timedelta(days=1)
for a,b in (('2025-10-07','2026-04-18'),('2026-09-30','2026-11-09')):
    for d in rng(a,b):
        p=f'hch/{d}.json'
        if os.path.exists(p): continue
        for k in range(3):
            try:
                r=json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.hockeychallengehelper.com/api/history?datetime={d}T00:00:00',headers=H),timeout=30)); break
            except Exception as e: r=None; time.sleep(2)
        if r is None: print('fail',d); continue
        json.dump(r,open(p,'w')); time.sleep(0.3)
print('done')
