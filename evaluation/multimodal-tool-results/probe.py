import base64, io, json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageDraw
from dotenv import load_dotenv
from figura.providers.config import ProviderSettings
from figura.providers.transport import OpenAISDKTransport, TransportNotice
load_dotenv('.env')
images=[]
for color,shape in [('red','circle'),('blue','square')]:
    im=Image.new('RGB',(256,256),'white'); d=ImageDraw.Draw(im)
    if shape=='circle': d.ellipse((40,40,216,216),fill=color)
    else: d.rectangle((40,40,216,216),fill=color)
    buf=io.BytesIO(); im.save(buf,format='PNG')
    images.append('data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode())
def probe(item):
    pid,p=item
    if not p.availability().available: return {'provider':pid.value,'status':'unconfigured'}
    calls=[{'id':f'call_{i}','type':'function','function':{'name':'inspect_image','arguments':'{}'}} for i in range(2)]
    messages=[{'role':'user','content':'Identify the visible color and shape in EACH tool result. Return concise JSON keyed by call_0 and call_1. Do not guess from metadata.'},{'role':'assistant','content':None,'tool_calls':calls}]
    for i,url in enumerate(images): messages.append({'role':'tool','tool_call_id':f'call_{i}','content':[{'type':'text','text':'Inspect this image.'},{'type':'image_url','image_url':{'url':url}}]})
    payload={'model':p.model_id,'messages':messages,'tools':[{'type':'function','function':{'name':'inspect_image','description':'Read an image.','parameters':{'type':'object','properties':{},'additionalProperties':False}}}], 'stream':True,'stream_options':{'include_usage':True},'max_tokens':200,'extra_body':{'thinking':{'type':'disabled'}}}
    if pid.value=='qwen': payload['extra_body']={'enable_thinking':False}
    text=''; usage=None
    try:
        for e in OpenAISDKTransport(p).create(**payload):
            if isinstance(e,TransportNotice): continue
            if e.get('usage'): usage=e['usage']
            for c in e.get('choices',[]): text+=c.get('delta',{}).get('content') or ''
        return {'provider':pid.value,'model':p.model_id,'status':'responded','answer':text,'usage':usage}
    except Exception as e:
        return {'provider':pid.value,'model':p.model_id,'status':'failed','error_type':type(e).__name__,'http_status':getattr(e,'status_code',None)}
with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(probe,ProviderSettings.from_env().profiles.items()))
Path('evaluation/multimodal-tool-results/probe-result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False))
