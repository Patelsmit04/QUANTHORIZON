import os
import sys
import traceback

# Ensure root directory is on sys.path for Vercel Serverless Function runtime
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

_app = None
_init_error = None

try:
    from app import app as _real_app
    _app = _real_app
except Exception as exc:
    _init_error = traceback.format_exc()
    print(f"[FATAL VERCEL BOOT ERROR]: {_init_error}", file=sys.stderr)


# Top-level ASGI entrypoint recognized by Vercel static AST analyzer
async def app(scope, receive, send):
    global _app, _init_error
    if _app is not None:
        await _app(scope, receive, send)
        return

    # If the real application failed to import, return exact diagnostic traceback
    if scope["type"] == "http":
        body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>TRADEXO — Serverless Initialization Diagnostic</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0B0E14;
            color: #E2E8F0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
            padding: 2.5rem 1.5rem;
            display: flex;
            justify-content: center;
        }}
        .container {{
            max-width: 900px;
            width: 100%;
            background: #151922;
            border: 1px solid #EF4444;
            border-radius: 12px;
            padding: 2rem;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
        }}
        .header {{
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 1px solid #2A303C;
            padding-bottom: 1rem;
            margin-bottom: 1.5rem;
        }}
        .badge {{
            background: rgba(239, 68, 68, 0.2);
            color: #EF4444;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 700;
        }}
        h1 {{ font-size: 1.4rem; color: #FFFFFF; }}
        p {{ color: #94A3B8; font-size: 0.95rem; line-height: 1.6; margin-bottom: 1rem; }}
        pre {{
            background: #0B0E14;
            border: 1px solid #2D3748;
            border-radius: 8px;
            padding: 1.25rem;
            color: #F87171;
            font-size: 0.85rem;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <span class="badge">STARTUP FAILURE</span>
            <h1>TRADEXO Engine Diagnostic</h1>
        </div>
        <p>The TRADEXO application was unable to complete its startup sequence in this Vercel Serverless Function execution environment.</p>
        <pre>{_init_error}</pre>
    </div>
</body>
</html>""".encode("utf-8")

        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"text/html; charset=utf-8"),
                (b"content-length", str(len(body)).encode("utf-8")),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })
