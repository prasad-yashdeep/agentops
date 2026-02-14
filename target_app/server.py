"""
Target App — An e-commerce API that AgentOps monitors.
Real endpoints, real business logic, real failures.
"""
import json
import os
import sys
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
HANDLER_PATH = os.path.join(os.path.dirname(__file__), "handler.py")
LOG_PATH = os.path.join(os.path.dirname(__file__), "app.log")

def log(level, msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {level}: {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log("ERROR", f"FATAL: Failed to parse config.json: {e}")
        raise
    except FileNotFoundError:
        log("ERROR", "FATAL: config.json not found!")
        raise

_handler_cache = None
_handler_mtime = 0

def load_handler():
    """Load handler module. Caches it and only reloads when the file changes.
    This preserves in-memory state (orders, stock) between requests,
    while still picking up fault injections (which modify the file).
    """
    global _handler_cache, _handler_mtime
    import importlib.util
    try:
        current_mtime = os.path.getmtime(HANDLER_PATH)
    except OSError:
        current_mtime = 0

    if _handler_cache is not None and current_mtime == _handler_mtime:
        return _handler_cache

    spec = importlib.util.spec_from_file_location("handler", HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _handler_cache = mod
    _handler_mtime = current_mtime
    log("INFO", f"Handler {'reloaded' if _handler_mtime else 'loaded'} (mtime={current_mtime})")
    return mod

REQUEST_COUNT = 0

class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global REQUEST_COUNT
        REQUEST_COUNT += 1
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path == "/health":
                config = load_config()
                handler = load_handler()
                handler.validate()
                self.respond(200, {
                    "status": "healthy",
                    "version": config.get("version", "1.0.0"),
                    "environment": config.get("environment", "production"),
                    "db_connected": bool(config.get("database_url")),
                    "cache_enabled": config.get("cache_enabled", True),
                    "uptime_seconds": round(time.time() - START_TIME, 1),
                    "requests_served": REQUEST_COUNT,
                })

            elif path == "/api/products":
                handler = load_handler()
                category = params.get("category", [None])[0]
                products = handler.get_products(category=category)
                self.respond(200, {"products": products, "count": len(products)})

            elif path == "/api/orders":
                handler = load_handler()
                orders = handler.get_orders()
                self.respond(200, {"orders": orders, "total_revenue": sum(o["total"] for o in orders)})

            elif path == "/api/analytics":
                handler = load_handler()
                analytics = handler.compute_analytics()
                self.respond(200, analytics)

            elif path == "/api/users":
                handler = load_handler()
                users = handler.get_users()
                self.respond(200, {"users": users, "count": len(users)})

            elif path.startswith("/api/products/"):
                product_id = int(path.split("/")[-1])
                handler = load_handler()
                product = handler.get_product_by_id(product_id)
                if product:
                    self.respond(200, product)
                else:
                    self.respond(404, {"error": f"Product {product_id} not found"})

            elif path == "/api/config":
                config = load_config()
                safe = {k: v for k, v in config.items()
                        if "secret" not in k.lower() and "password" not in k.lower() and "key" not in k.lower()}
                self.respond(200, safe)

            else:
                self.respond(404, {"error": "Not found", "path": path})

        except json.JSONDecodeError as e:
            log("ERROR", f"CONFIG PARSE ERROR on {path}: {e}")
            self.respond(500, {"error": "Configuration error", "detail": str(e), "type": "ConfigParseError"})
        except Exception as e:
            tb = traceback.format_exc()
            log("ERROR", f"UNHANDLED EXCEPTION on GET {path}: {e}\n{tb}")
            self.respond(500, {"error": str(e), "type": type(e).__name__, "traceback": tb})

    def do_POST(self):
        global REQUEST_COUNT
        REQUEST_COUNT += 1
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/api/orders":
                handler = load_handler()
                order = handler.create_order(body)
                log("INFO", f"New order created: #{order['id']} total=${order['total']:.2f}")
                self.respond(201, order)

            elif path == "/api/checkout":
                handler = load_handler()
                result = handler.process_checkout(body)
                log("INFO", f"Checkout processed: {result.get('status')}")
                self.respond(200, result)

            elif path == "/api/users":
                handler = load_handler()
                user = handler.create_user(body)
                log("INFO", f"New user registered: {user['name']}")
                self.respond(201, user)

            else:
                self.respond(404, {"error": "Not found"})

        except Exception as e:
            tb = traceback.format_exc()
            log("ERROR", f"UNHANDLED EXCEPTION on POST {self.path}: {e}\n{tb}")
            self.respond(500, {"error": str(e), "type": type(e).__name__, "traceback": tb})

    def respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def do_OPTIONS(self):
        self.respond(200, {})

    def log_message(self, format, *args):
        pass

START_TIME = time.time()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    log("INFO", f"🚀 E-Commerce API starting on port {port}")
    log("INFO", f"   Config: {CONFIG_PATH}")
    log("INFO", f"   Handler: {HANDLER_PATH}")
    log("INFO", f"   Endpoints: /health, /api/products, /api/orders, /api/analytics, /api/users, /api/checkout")
    server = HTTPServer(("0.0.0.0", port), AppHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("INFO", "Shutting down gracefully")
