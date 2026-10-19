from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from pathlib import Path
import json,mimetypes
ROOT=Path('/tmp/eios-test/geo-r1-20261012/ui').resolve()
class H(BaseHTTPRequestHandler):
 def do_GET(self): self.proxy()
 def do_POST(self): self.proxy()
 def do_PUT(self): self.proxy()
 def do_DELETE(self): self.proxy()
 def do_PATCH(self): self.proxy()
 def log_message(self,*args): pass
 def proxy(self):
  path=self.path.split('?')[0]
  if path.startswith('/api/product/geo'):
   self.send_response(503);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"ok":false,"error":{"code":"UI_PREVIEW_ONLY","message":"Isolated UI preview"}}');return
  if path.startswith('/product/geo/'):
   file=(ROOT/path[len('/product/geo/'):]).resolve()
   if ROOT not in file.parents and file!=ROOT: self.send_error(403);return
   if file.is_dir(): file=file/'index.html'
   if not file.exists(): self.send_error(404);return
   data=file.read_bytes();ctype=mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
   if file.name=='index.html': data=data.replace(b'<head>',b'<head><script>localStorage.setItem("eios-geo-demo-fixtures","on")</script>')
   self.send_response(200);self.send_header('Content-Type',ctype);self.end_headers();self.wfile.write(data);return
  headers={k:v for k,v in self.headers.items() if k.lower() not in ('host','connection','accept-encoding')}
  size=int(self.headers.get('Content-Length','0'));body=self.rfile.read(size) if size else None
  try: r=urlopen(Request('http://127.0.0.1:4173'+self.path,data=body,headers=headers,method=self.command))
  except HTTPError as e:r=e
  data=r.read();ctype=r.headers.get('Content-Type','')
  if path=='/api/product/availability' and r.status==200:
   obj=json.loads(data)
   for item in obj.get('items',[]):
    if item.get('product_id')=='geo':item.update(status='available',available=True,operable=False,reason_code='ISOLATED_UI_PREVIEW')
   data=json.dumps(obj).encode()
  if 'text/html' in ctype and not path.startswith('/product/'):
   data=data.replace(b'<head>','<head><style>body:before{content:"GEO UI \u9694\u79bb\u9884\u89c8 \u00b7 \u6f14\u793a\u6570\u636e \u00b7 GEO \u4e1a\u52a1\u8bf7\u6c42\u5df2\u963b\u65ad";display:block;position:fixed;bottom:0;left:0;right:0;z-index:9999;text-align:center;background:#fff3cc;color:#79601b;padding:5px;font-size:11px}</style>'.encode())
  self.send_response(r.status)
  for k,v in r.headers.items():
   if k.lower() not in ('content-length','transfer-encoding','connection','content-encoding'): self.send_header(k,v)
  self.end_headers();self.wfile.write(data)
ThreadingHTTPServer(('127.0.0.1',43818),H).serve_forever()
