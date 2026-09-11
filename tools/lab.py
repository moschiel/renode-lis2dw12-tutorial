"""Run a small read-only web view of the LIS2DW12 model and firmware UART."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import webbrowser

from renode_client import ROOT, Renode


class Lab:
    def __init__(self, renode):
        self.renode = renode
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.error = None
        renode.advance(.05)
        self.snapshot = renode.state()

    def work(self):
        while not self.stop.wait(.05):
            try:
                with self.lock:
                    self.renode.advance(.05)
                    self.snapshot = self.renode.state()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                self.stop.set()

    def state(self):
        with self.lock:
            return dict(self.snapshot, error=self.error)


def handler_for(lab):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/api/state':
                payload = json.dumps(lab.state()).encode()
                content_type = 'application/json'
            elif self.path in ('/', '/index.html'):
                payload = (ROOT / 'web/index.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renode', help='Renode executable path')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    with Renode(args.renode) as renode:
        lab = Lab(renode)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(lab))
        worker = threading.Thread(target=lab.work, daemon=True)
        worker.start()
        url = 'http://127.0.0.1:%d' % server.server_port
        print('LIS2DW12 view: %s (Ctrl+C to stop)' % url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass
        finally:
            lab.stop.set()
            server.server_close()
            worker.join(timeout=5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
