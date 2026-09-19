import json

from sqlalchemy import select

from app.config import settings
from app.db import Event, read_case, session


def export_case(case_id: str):
    folder = settings().media_root / "replays"
    folder.mkdir(parents=True, exist_ok=True)
    case = read_case(case_id)
    with session() as db:
        events = db.scalars(select(Event).where(Event.case_id == case_id).order_by(Event.sequence)).all()
        recording = {"schema_version": 1, "replay": True, "case": case, "events": [
            {"sequence": e.sequence, "created_at": e.created_at.isoformat(), "payload": e.payload}
            for e in events
        ]}
    raw = json.dumps(recording, ensure_ascii=False)
    (folder / f"{case_id}.json").write_text(raw)
    # Inline data is escaped for HTML script contexts; display uses textContent, never innerHTML.
    embedded = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HypeCheck · offline replay</title><style>
body{font:16px system-ui;background:#f6f5ef;color:#153b35;max-width:900px;margin:40px auto;padding:20px}
article{background:white;padding:24px;border:1px solid #d6dfd9;margin:20px 0;border-radius:16px}
blockquote{border-left:3px solid #517f54;padding:16px;background:#edf3e9;white-space:pre-wrap}
button{padding:12px;border-radius:8px;border:1px solid #153b35;background:#153b35;color:white;cursor:pointer}
small{display:block;color:#5c6b64} a{color:#195f51} pre{white-space:pre-wrap} h1{font-size:40px}
</style><h1>HypeCheck</h1><p>OFFLINE REPLAY · Recorded results, not a live analysis.</p>
<button id="play">Replay recorded progress</button><p id="status"></p><main id="results"></main>
<script id="data" type="application/json">DATA_PLACEHOLDER</script><script>
const recording=JSON.parse(document.getElementById('data').textContent);
const results=document.getElementById('results');const status=document.getElementById('status');
function add(parent,tag,text){const el=document.createElement(tag);el.textContent=text;parent.append(el);return el;}
function render(c){status.textContent=c.status+' · '+c.result.model_mode+' model mode';results.replaceChildren();
if(c.error)add(results,'p',c.error.message);
for(const item of Object.values(c.result.claims||{})){const card=add(results,'article','');add(card,'h2',item.claim.text);
add(card,'p',item.verdict?.label||item.status);add(card,'p',item.verdict?.explanation||item.error||'');
for(const p of item.evidence||[]){add(card,'h3',p.title);add(card,'small',p.access_type+' · '+p.section);
add(card,'blockquote',p.text);const a=add(card,'a','Open source');
if(p.source_url.startsWith('https://europepmc.org/')){a.href=p.source_url;a.target='_blank';a.rel='noopener noreferrer';}}
}}
render(recording.case);let playing=false;
document.getElementById('play').onclick=async()=>{if(playing)return;playing=true;const btn=document.getElementById('play');btn.disabled=true;
let previous=null;for(const event of recording.events){const at=Date.parse(event.created_at);
if(previous!==null)await new Promise(resolve=>setTimeout(resolve,Math.max(0,at-previous)));
render(event.payload);previous=at;}render(recording.case);btn.disabled=false;playing=false;};
</script></html>""".replace("DATA_PLACEHOLDER", embedded)
    (folder / f"{case_id}.html").write_text(html)
    return folder / f"{case_id}.html"
