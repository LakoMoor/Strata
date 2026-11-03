"""Integration checks for real HTTP forwarding, SSE delivery and control safety."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

spec=importlib.util.spec_from_file_location('dashboard',Path(__file__).parents[1]/'server.py')
dash=importlib.util.module_from_spec(spec);spec.loader.exec_module(dash)

class Backend(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*a):pass
    def do_GET(self):
        body=json.dumps({'live':{'state':'idle','queued':0}} if self.path=='/metrics' else {'status':'ok','loaded':True}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length',0)))
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n');self.wfile.flush()
        self.server.first.set();self.server.release.wait(5)
        self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=Path(self.tmp.name)/'engine.json'
        self.cfg.write_text(json.dumps({'host':'127.0.0.1','api_key':'','args':['--max-context','262144','--kv-resident','32768','--spec','4','--spec-min-p','0.5']}))
        self.backend=dash.HTTPServer(('127.0.0.1',0),Backend)
        self.backend.first=threading.Event();self.backend.release=threading.Event()
        threading.Thread(target=self.backend.serve_forever,daemon=True).start()
        self.controller=dash.Controller(self.cfg,'unused',self.backend.server_port)
        self.gateway=dash.HTTPServer(('127.0.0.1',0),dash.Handler);self.gateway.controller=self.controller
        threading.Thread(target=self.gateway.serve_forever,daemon=True).start()
    def tearDown(self):
        self.backend.release.set();self.gateway.shutdown();self.backend.shutdown();self.gateway.server_close();self.backend.server_close();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.gateway.server_port,timeout=5)
        h={'Content-Type':'application/json',**(headers or {})}
        c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();code=r.status;data=r.read();c.close();return code,data
    def test_invalid_config_is_atomic_and_paths_are_not_editable(self):
        old=self.cfg.read_bytes()
        for change in ({'context':100},{'context':32768,'max_tokens':65536},{'spec':True},{'spec':float('nan')},{'exe':'/bin/evil'},{'thinking':'yes'}):
            code,_=self.request('/dashboard/settings',change);self.assertEqual(code,400);self.assertEqual(old,self.cfg.read_bytes())
        code,body=self.request('/dashboard/settings',{'temperature':0.2,'max_tokens':1024})
        self.assertEqual(code,200);self.assertEqual(json.loads(body)['settings']['max_tokens'],1024)
        self.assertTrue(self.controller.pending);self.assertEqual(json.loads(self.cfg.read_text())['shared_defaults']['reasoning_effort'],'none')
    def test_browser_cross_origin_controls_rejected(self):
        code,_=self.request('/dashboard/control',{'action':'stop'},{'Origin':'http://other.example'})
        self.assertEqual(code,403)
    def test_no_key_api_and_static_dashboard(self):
        self.assertEqual(self.request('/health')[0],200)
        code,data=self.request('/');self.assertEqual(code,200);self.assertIn(b'Inference Studio',data)
        code,data=self.request('/dashboard/status');self.assertFalse(json.loads(data)['auth'])
    def test_streaming_does_not_buffer_and_restart_cannot_interrupt(self):
        c=http.client.HTTPConnection('127.0.0.1',self.gateway.server_port,timeout=3)
        c.request('POST','/v1/chat/completions','{}',{'Content-Type':'application/json'})
        r=c.getresponse();self.assertEqual(r.status,200)
        self.assertTrue(self.backend.first.wait(2))
        self.assertIn(b'first',r.readline()) # arrives before backend finishes
        self.assertFalse(self.backend.release.is_set())
        code,body=self.request('/dashboard/control',{'action':'restart'})
        self.assertEqual(code,400);self.assertIn('активные',json.loads(body)['error']['message'])
        self.backend.release.set();self.assertIn(b'[DONE]',r.read());c.close()
    def test_busy_backend_prevents_stop(self):
        self.controller.backend=lambda *a,**k:{'live':{'state':'generating','queued':1}}
        code,_=self.request('/dashboard/control',{'action':'stop'});self.assertEqual(code,400)
        self.assertIsNone(self.controller.action)
    def test_control_gate_rejects_new_inference(self):
        self.controller.action='restart'
        code,_=self.request('/v1/chat/completions',{})
        self.assertEqual(code,503)
    def test_native_mutation_cannot_bypass_controller(self):
        for path in ('/config','/settings','/unload','/v1/unload'):
            self.assertEqual(self.request(path,{})[0],404)

if __name__=='__main__':unittest.main()
