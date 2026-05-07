"""Serves the dashboard at http://localhost:8080"""
import http.server, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from constants import DASHBOARD_PORT

os.chdir(os.path.dirname(os.path.abspath(__file__)))
handler = http.server.SimpleHTTPRequestHandler
with http.server.HTTPServer(("", DASHBOARD_PORT), handler) as srv:
    print(f"Dashboard → http://localhost:{DASHBOARD_PORT}")
    srv.serve_forever()
