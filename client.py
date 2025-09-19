# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if you have not received it, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import json
import socket
import threading
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
import logging
import bpy

bk_logger = logging.getLogger(__name__)


def handle_login_response(api_key: str, error: str = None):
    """Handles the API key received from callback. Stores it if successful, logs out on error."""
    preferences = bpy.context.preferences.addons[__package__].preferences
    preferences.login_attempt = False
    if api_key:
        preferences.api_key = api_key
        bk_logger.info("API key stored successfully.")
    else:
        preferences.api_key = ""
        bk_logger.error(f"Login failed: {error}")

ALLOWED_ORIGIN = "http://localhost:3005"
class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        requested_headers = self.headers.get("Access-Control-Request-Headers")
        if requested_headers:
            self.send_header("Access-Control-Allow-Headers", requested_headers)
        else:
            self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        """Handle preflight OPTIONS requests for CORS."""
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()
        bk_logger.debug("Sent OPTIONS response")

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/callback":
            query_params = parse_qs(parsed_path.query)
            api_key = query_params.get("api_key")
            if api_key:
                response_body = {"message": "Login successful", "success": True}
                response_body_bytes = json.dumps(response_body).encode('utf-8')
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body_bytes)))
                self.end_headers()
                self.wfile.write(response_body_bytes)
                handle_login_response(api_key[0])
                bk_logger.debug("Sent 200 response with API key")
            else:
                response_body = {"message": "No API key provided", "success": False}
                response_body_bytes = json.dumps(response_body).encode('utf-8')
                self.send_response(400)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body_bytes)))
                self.end_headers()
                self.wfile.write(response_body_bytes)
                handle_login_response(None, "No API key provided")
                bk_logger.debug("Sent 400 response: No API key")
            return
        response_body = {"message": "Not Found", "success": False}
        response_body_bytes = json.dumps(response_body).encode('utf-8')
        self.send_response(404)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body_bytes)))
        self.end_headers()
        self.wfile.write(response_body_bytes)
        bk_logger.debug("Sent 404 response")


_server = None
_server_thread = None
_stop_event = threading.Event()


def get_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        return s.getsockname()[1]


def start_server(callback_url):
    global _server, _server_thread
    port = urlparse(callback_url).port
    bk_logger.debug(
        f"Starting server with callback_url: {callback_url}, type: {type(callback_url)}"
    )
    _server = socketserver.TCPServer(("", port), CallbackHandler)
    _stop_event.clear()
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    bk_logger.info(f"Started server on port {port}")


def stop_server():
    global _server
    if _server:
        _stop_event.set()
        _server.shutdown()
        _server.server_close()
        _server = None
        bk_logger.info("Server stopped")
