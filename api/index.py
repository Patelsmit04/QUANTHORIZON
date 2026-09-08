import os
import sys
import traceback

# Ensure root directory is on sys.path for Vercel Serverless Function runtime
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

_boot_exception_str = None
_boot_traceback = None

try:
    from app import app
except Exception as exc:
    _boot_exception_str = str(exc)
    _boot_traceback = traceback.format_exc()
    print(f"[FATAL VERCEL BOOT ERROR]: {_boot_traceback}", file=sys.stderr)

    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="TRADEXO — Serverless Initialization Diagnostic")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
    async def diagnostic_handler(request: Request, full_path: str = ""):
        is_api = full_path.startswith("api/") or "application/json" in request.headers.get("accept", "")
        if is_api:
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "code": "SERVERLESS_INITIALIZATION_FAILED",
                    "message": "TRADEXO backend failed to initialize on Vercel.",
                    "exception": _boot_exception_str,
                    "traceback": _boot_traceback.splitlines() if _boot_traceback else []
                }
            )

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>TRADEXO — Serverless Startup Diagnostic</title>
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
        .hint {{
            margin-top: 1.5rem;
            background: rgba(59, 130, 246, 0.1);
            border-left: 4px solid #3B82F6;
            padding: 1rem;
            border-radius: 4px;
            font-size: 0.9rem;
            color: #93C5FD;
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
        <p><strong>Exception:</strong> {_boot_exception_str}</p>
        <pre>{_boot_traceback}</pre>
        <div class="hint">
            <strong>Troubleshooting Hint:</strong> Verify that all required Python dependencies are listed in <code>requirements.txt</code> and all project modules are committed to git.
        </div>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content, status_code=500)
