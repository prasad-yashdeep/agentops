"""
Target App — A real running API that AgentOps monitors.
This is the "production" service. Faults are injected by modifying
its source files / config. The agent detects, diagnoses, and fixes.
"""
import json
import os
import sys
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
HANDLER_PATH = os.path.join(os.path.dirname(__file__), "handler.py")
LOG_PATH = os.path.join(os.path.dirname(__file__), "app.log")

def log(level, msg):
    """Write to both stdout and log file."""
    line = f"[{time.strftime('%H:%M:%S')}] {level}: {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log("ERROR", f"Failed to parse config.json: {e}")
        raise
    except FileNotFoundError:
        log("ERROR", "config.json not found")
        raise


def load_handler():
    """Dynamically load handler.py so injected bugs are picked up."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("handler", HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == "/health":
                config = load_config()
                handler = load_handler()
                # Verify handler works
                handler.validate()
                self.respond(200, {
                    "status": "healthy",
                    "version": config.get("version", "1.0.0"),
                    "db_connected": bool(config.get("database_url")),
                    "uptime": time.time() - START_TIME,
                })

            elif self.path == "/api/users":
                handler = load_handler()
                users = handler.get_users()
                self.respond(200, {"users": users, "count": len(users)})

            elif self.path == "/api/stats":
                handler = load_handler()
                stats = handler.compute_stats()
                self.respond(200, stats)

            elif self.path == "/api/config":
                config = load_config()
                # Redact sensitive fields
                safe = {k: v for k, v in config.items() if "secret" not in k.lower() and "password" not in k.lower()}
                self.respond(200, safe)

            else:
                self.respond(404, {"error": "Not found"})

        except json.JSONDecodeError as e:
            log("ERROR", f"CONFIG PARSE ERROR: {e}")
            self.respond(500, {
                "error": "Configuration error",
                "detail": str(e),
                "type": "ConfigParseError",
            })
        except Exception as e:
            tb = traceback.format_exc()
            log("ERROR", f"UNHANDLED EXCEPTION on {self.path}: {e}\n{tb}")
            self.respond(500, {
                "error": str(e),
                "type": type(e).__name__,
                "traceback": tb,
            })

    def do_POST(self):
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}

            if self.path == "/api/process":
                handler = load_handler()
                result = handler.process_data(body)
                self.respond(200, {"result": result})
            else:
                self.respond(404, {"error": "Not found"})

        except Exception as e:
            tb = traceback.format_exc()
            log("ERROR", f"UNHANDLED EXCEPTION on POST {self.path}: {e}\n{tb}")
            self.respond(500, {
                "error": str(e),
                "type": type(e).__name__,
                "traceback": tb,
            })

    def respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logging


START_TIME = time.time()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    log("INFO", f"Target app starting on port {port}")
    log("INFO", f"Config: {CONFIG_PATH}")
    log("INFO", f"Handler: {HANDLER_PATH}")
    server = HTTPServer(("127.0.0.1", port), AppHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("INFO", "Shutting down")
