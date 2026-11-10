#!/usr/bin/env python3
"""A small persistent counter for a Pacemaker-managed filesystem."""
import argparse
from contextlib import closing
import html
import json
import socket
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Counter:
    def __init__(self, database: Path):
        self.database = Path(database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY CHECK (id = 1), value INTEGER NOT NULL)')
            connection.execute('INSERT OR IGNORE INTO counter VALUES (1, 0)')

    def value(self) -> int:
        with closing(sqlite3.connect(self.database, timeout=10)) as connection, connection:
            return connection.execute('SELECT value FROM counter WHERE id = 1').fetchone()[0]

    def increment(self) -> None:
        with closing(sqlite3.connect(self.database, timeout=10)) as connection, connection:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('UPDATE counter SET value = value + 1 WHERE id = 1')


def run_counter(counter: Counter, stop: threading.Event) -> None:
    """Persist a tick every half second until stopped."""
    while not stop.wait(0.5):
        counter.increment()


def create_server(host: str, port: int, database: Path) -> ThreadingHTTPServer:
    counter = Counter(database)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/', '/health', '/state'):
                self.send_error(404)
                return
            value = counter.value()
            if self.path == '/health':
                body = b'ok\n'
                content_type = 'text/plain; charset=utf-8'
            elif self.path == '/state':
                body = json.dumps({'value': value, 'node': socket.gethostname()}).encode()
                content_type = 'application/json; charset=utf-8'
            else:
                node = html.escape(socket.gethostname())
                body = (f'<!doctype html><html><head><meta charset="utf-8"><title>HA counter</title></head>'
                        f'<body><h1>HA counter</h1><p>Active node: <span id="node">{node}</span></p>'
                        f'<p>Counter: <strong id="value">{value}</strong></p>'
                        '<p id="status"></p><form method="post" action="/increment">'
                        '<button type="submit">Increment</button></form>'
                        '<script>async function update() { try { const r = await fetch("/state", {cache: "no-store"});'
                        ' if (!r.ok) throw Error(); const data = await r.json();'
                        ' document.getElementById("value").textContent = data.value;'
                        ' document.getElementById("node").textContent = data.node;'
                        ' document.getElementById("status").textContent = "";'
                        ' } catch (_) { document.getElementById("status").textContent = "Reconnecting..."; }'
                        ' finally { setTimeout(update, 500); } } setTimeout(update, 500);</script></body></html>').encode()
                content_type = 'text/html; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/increment':
                self.send_error(404)
                return
            counter.increment()
            self.send_response(303)
            self.send_header('Location', '/')
            self.send_header('Content-Length', '0')
            self.end_headers()

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.database)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run_counter(Counter(args.database), threading.Event())
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
