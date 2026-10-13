import os
from http.server import BaseHTTPRequestHandler,HTTPServer

def healthy():return os.environ.get('HEALTHY','1')=='1'
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ok=self.path=='/health' and healthy()
        self.send_response(200 if ok else 503);self.end_headers()
        self.wfile.write(b'AgentShell isolated acceptance fixture\n')
    def log_message(self,*args):pass
if __name__=='__main__':HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
