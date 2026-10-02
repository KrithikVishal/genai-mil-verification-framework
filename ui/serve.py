"""
serve.py
--------
Lightweight local HTTP server for the Autonomous MIL Verification UI.
Runs on localhost:8080 (or next free port) and automatically opens the browser.
"""

import http.server
import socketserver
import webbrowser
import os
import sys

PORT = 8080
UI_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

def main():
    os.chdir(UI_DIR)
    
    # Attempt to bind to PORT or PORT+1
    port = PORT
    httpd = None
    for p in range(PORT, PORT + 10):
        try:
            httpd = socketserver.TCPServer(("", p), Handler)
            port = p
            break
        except OSError:
            continue
            
    if not httpd:
        print(f"Error: Could not bind to any port between {PORT} and {PORT+10}")
        sys.exit(1)

    url = f"http://localhost:{port}/index.html"
    print("=" * 65)
    print("  AUTONOMOUS MIL VERIFICATION ENGINE — WEB DASHBOARD")
    print("=" * 65)
    print(f"  Server running at:  {url}")
    print("  Theme:              Monochrome (Black, White & Grey)")
    print("  Interactive:        9 Closed-Loop Verification Stages")
    print("  Press Ctrl+C to stop the server.")
    print("=" * 65)

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        httpd.server_close()

if __name__ == "__main__":
    main()
