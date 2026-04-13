#!/usr/bin/env python3
"""Minimal HTTP server for the ChessVision dashboard output folder."""
import os, http.server, socketserver

PORT = 5050
DIR  = os.path.join(os.path.dirname(__file__), "output")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)
    def log_message(self, fmt, *args):
        pass   # silence access logs

print(f"ChessVision dashboard → http://localhost:{PORT}/dashboard.html")
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    httpd.serve_forever()
