#!/usr/bin/env python3
"""Opt-in Strata dashboard and streaming gateway. No third-party dependencies."""
import argparse
import copy
import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from socketserver import TCPServer

ROOT = Path(__file__).resolve().parent
# Only these engine arguments may be changed over HTTP. Paths and commands stay private.
FIELDS = {
    'context': ('--max-context', 8192, 262144, int),
    'kv_resident': ('--kv-resident', 4096, 32768, int),
    'spec': ('--spec', 0, 8, int),
    'spec_min_p': ('--spec-min-p', 0, 1, float),
}
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def flag(args, name, default):
    return args[args.index(name) + 1] if name in args else default


class Controller:
    def __init__(self, config, python, backend_port):
        self.config = Path(config).resolve()
        self.python = python
        self.port = backend_port
        self.lock = threading.RLock()
        self.process = None
        self.state = 'stopped'
        self.error = None
        self.pending = False
        self.action = None
        self.started = None
        self.in_flight = 0
        self.log = self.config.parent / 'dashboard-backend.log'
        cfg = read_json(self.config)
        if cfg.get('api_key') or cfg.get('host') != '127.0.0.1':
            raise ValueError('Dashboard backend config must bind 127.0.0.1 without api_key')

    def backend(self, path, method='GET', body=None, timeout=3):
        con = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        try:
            headers = {'Content-Type': 'application/json', 'Host': f'127.0.0.1:{self.port}'}
            con.request(method, path, json.dumps(body) if body is not None else None, headers)
            res = con.getresponse()
            result = json.loads(res.read())
            if res.status >= 400:
                raise ValueError(str(result.get('error', result)))
            return result
        finally:
            con.close()

    def settings(self):
        cfg = read_json(self.config)
        args = cfg['args']
        values = {key: kind(flag(args, option, lo)) for key, (option, lo, _, kind) in FIELDS.items()}
        values.update(temperature=cfg.get('sampling', {}).get('temperature', 0.7),
                      max_tokens=(cfg.get('shared_defaults') or {}).get('max_tokens', 65536),
                      thinking=(cfg.get('shared_defaults') or {}).get('reasoning_effort') == 'high')
        return values

    def save(self, changes):
        with self.lock:
            if self.action:
                raise ValueError('Дождитесь завершения текущей операции')
            allowed = set(FIELDS) | {'temperature', 'max_tokens', 'thinking'}
            if not isinstance(changes, dict) or not changes or set(changes) - allowed:
                raise ValueError('Неизвестные или пустые настройки')
            merged = {**self.settings(), **changes}
            checks = {**FIELDS, 'temperature': ('', 0, 2, float), 'max_tokens': ('', 1, 65536, int)}
            for key, (_, lo, hi, kind) in checks.items():
                v = merged[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi or (kind is int and int(v) != v):
                    raise ValueError(f'{key}: допустимо {lo}–{hi}')
            if not isinstance(merged['thinking'], bool):
                raise ValueError('thinking: требуется true/false')
            if merged['kv_resident'] > merged['context'] or merged['max_tokens'] >= merged['context']:
                raise ValueError('KV и генерация должны помещаться в контекст; оставьте место для запроса')
            cfg = read_json(self.config)
            cfg = copy.deepcopy(cfg)
            args = cfg['args']
            for key, (option, _, _, kind) in FIELDS.items():
                value = str(kind(merged[key]))
                if option in args:
                    args[args.index(option) + 1] = value
                else:
                    args.extend([option, value])
            cfg['sampling'] = {**cfg.get('sampling', {}), 'temperature': merged['temperature']}
            cfg['shared_defaults'] = {'temperature': merged['temperature'], 'max_tokens': merged['max_tokens'],
                                      'reasoning_effort': 'high' if merged['thinking'] else 'none'}
            write_json(self.config.with_suffix('.bak.json'), read_json(self.config))
            write_json(self.config, cfg)
            self.pending = True
            return self.settings()

    def status(self):
        with self.lock:
            if self.process and self.process.poll() is not None and not self.action:
                self.state = 'error'
                self.error = f'Backend exited ({self.process.returncode}); see dashboard-backend.log'
            result = {'state': self.state, 'action': self.action, 'error': self.error,
                      'pending': self.pending, 'uptime': round(time.time() - self.started) if self.started else 0,
                      'auth': False, 'settings': self.settings()}
        try:
            result['health'] = self.backend('/health')
            result['state'] = 'running' if result['health'].get('loaded') else 'unloaded'
            if self.action:
                result['state'] = self.state
        except (OSError, ValueError, http.client.HTTPException):
            pass
        return result

    def request_action(self, action):
        if action not in ('start', 'stop', 'restart', 'load', 'unload'):
            raise ValueError('Неизвестная операция')
        with self.lock:
            if self.action:
                raise ValueError('Операция уже выполняется')
            if self.in_flight:
                raise ValueError('Есть активные запросы. Дождитесь их завершения')
            # Never interrupt a generation or drop its queued clients.
            if action in ('stop', 'restart', 'unload'):
                try:
                    live = self.backend('/metrics').get('live', {})
                    if live.get('state') not in (None, 'idle', 'unloaded') or live.get('queued', 0):
                        raise ValueError('Модель занята. Дождитесь завершения запросов')
                except (OSError, http.client.HTTPException):
                    pass
            self.action = action
            threading.Thread(target=self._perform, args=(action,), daemon=True).start()

    def stop(self):
        p = self.process
        if p and p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=10)
        self.process = None
        self.state = 'stopped'
        self.started = None

    def _perform(self, action):
        try:
            self.error = None
            if action in ('restart', 'stop'):
                self.state = 'stopping'
                self.stop()
            if action in ('start', 'restart'):
                if self.process and self.process.poll() is None:
                    raise ValueError('Сервер уже запущен')
                cfg = read_json(self.config)
                env = {**os.environ, **cfg.get('env', {})}
                self.state = 'starting'
                with self.log.open('ab') as log:
                    self.process = subprocess.Popen([self.python, '-m', 'serve.server', '--engine', 'strata',
                        '--config', str(self.config), '--host', '127.0.0.1', '--port', str(self.port), '--parallel', '1'],
                        cwd=cfg['cwd'], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                self.started = time.time()
                deadline = time.monotonic() + 1000
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise RuntimeError(f'Backend exited ({self.process.returncode}); see dashboard-backend.log')
                    try:
                        health = self.backend('/health')
                        if health.get('status') == 'ok':
                            if cfg.get('shared_defaults'):
                                self.backend('/settings', 'POST', {'defaults': cfg['shared_defaults']})
                            self.state = 'running'
                            self.pending = False
                            break
                    except (OSError, ValueError, http.client.HTTPException):
                        pass
                    time.sleep(1)
                else:
                    self.stop()
                    raise RuntimeError('Backend readiness timeout (1000s)')
            if action in ('load', 'unload'):
                self.state = 'loading' if action == 'load' else 'unloading'
                self.backend('/' + action, 'POST', {}, timeout=1000)
                self.state = 'running' if action == 'load' else 'unloaded'
        except Exception as e:
            self.error = str(e)
            self.state = 'error'
        finally:
            self.action = None


class HTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # No reverse DNS: the listener must not depend on a host's DNS configuration.
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    server_version = 'StrataDashboard/1.0'

    def log_message(self, fmt, *args):
        if self.path.startswith('/dashboard/') or self.path == '/':
            super().log_message(fmt, *args)

    def json(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def body(self, limit):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Use Content-Length, chunked request bodies are not supported')
        n = int(self.headers.get('Content-Length', '0'))
        if n < 0 or n > limit:
            raise ValueError('Request body is too large')
        return self.rfile.read(n)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/dashboard/status':
            return self.json(200, self.server.controller.status())
        assets = {'/': ('index.html', 'text/html'), '/dashboard/app.js': ('app.js', 'text/javascript'),
                  '/dashboard/style.css': ('style.css', 'text/css')}
        if path in assets:
            name, mime = assets[path]
            data = (ROOT / 'web' / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)
            return
        self.proxy()

    def do_POST(self):
        # No key by explicit user request. Still disallow cross-site browser mutations.
        origin = self.headers.get('Origin', '')
        if (origin and urlsplit(origin).netloc != self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.json(403, {'error': {'message': 'Cross-origin requests are not allowed'}})
        path = urlsplit(self.path).path
        if path in ('/dashboard/control', '/dashboard/settings'):
            try:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Content-Type must be application/json')
                req = json.loads(self.body(16384))
                if not isinstance(req, dict):
                    raise ValueError('Expected a JSON object')
                if path.endswith('/control'):
                    self.server.controller.request_action(req.get('action'))
                    return self.json(202, {'accepted': True})
                return self.json(200, {'settings': self.server.controller.save(req)})
            except (ValueError, TypeError) as e:
                return self.json(400, {'error': {'message': str(e)}})
        self.proxy()

    def do_OPTIONS(self):
        self.proxy()

    def proxy(self):
        controller = self.server.controller
        admitted = self.command == 'POST'
        if admitted:
            if not urlsplit(self.path).path.startswith('/v1/'):
                return self.json(404, {'error': {'message': 'Use /dashboard/control or /dashboard/settings'}})
            if urlsplit(self.path).path.rstrip('/') in ('/v1/load', '/v1/unload'):
                return self.json(404, {'error': {'message': 'Use /dashboard/control'}})
            with controller.lock:
                if controller.action:
                    return self.json(503, {'error': {'message': 'Server control operation in progress; retry later'}})
                controller.in_flight += 1
        con = http.client.HTTPConnection('127.0.0.1', controller.port, timeout=1000)
        begun = False
        try:
            body = self.body(32 * 1024 * 1024) if self.command == 'POST' else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP | {'host', 'authorization', 'origin'}}
            headers['Host'] = f'127.0.0.1:{self.server.controller.port}'
            con.request(self.command, self.path, body, headers)
            res = con.getresponse()
            self.send_response(res.status)
            for k, v in res.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header('Connection', 'close')
            self.end_headers()
            begun = True
            self.close_connection = True
            while True:
                data = res.read1(65536)
                if not data:
                    break
                self.wfile.write(data)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as e:
            if not begun:
                self.json(400, {'error': {'message': str(e)}})
        except (OSError, http.client.HTTPException):
            if not begun:
                self.json(503, {'error': {'message': 'Strata backend is starting or stopped. See /dashboard/status.'}})
        finally:
            con.close()
            if admitted:
                with controller.lock:
                    controller.in_flight -= 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    p.add_argument('--python', required=True)
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=8000)
    p.add_argument('--backend-port', type=int, default=18080)
    p.add_argument('--no-start', action='store_true')
    args = p.parse_args()
    c = Controller(args.config, args.python, args.backend_port)
    server = HTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.controller = c
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    if not args.no_start:
        c.request_action('start')
    pidfile = c.config.parent / 'dashboard.pid'
    pidfile.write_text(str(os.getpid()))
    print(f'Strata dashboard listening on {args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        c.stop()
        server.server_close()
        if pidfile.exists() and pidfile.read_text() == str(os.getpid()):
            pidfile.unlink()


if __name__ == '__main__':
    main()
