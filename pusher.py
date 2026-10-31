# mirrors local engine /api to Render /ingest every 2s
import os,time,urllib.request
TOK=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),".mirror_token")).read().strip()
DST=os.environ.get("MIRROR_URL","https://pumpbot-yea4.onrender.com/ingest")
while True:
    try:
        b=urllib.request.urlopen("http://127.0.0.1:8811/api",timeout=5).read()
        urllib.request.urlopen(urllib.request.Request(DST,data=b,method="POST",headers={"Authorization":"Bearer "+TOK,"Content-Type":"application/json"}),timeout=10).read()
    except Exception as e: print(time.strftime("%H:%M:%S"),"push err:",e,flush=True)
    time.sleep(2)
