# -*- coding: utf-8 -*-
import html
import traceback

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError

from odoo.addons.website_sale.controllers.main import WebsiteSale


def _extract_origin(tb_text):
    """
    Try to find the most relevant frame from addons (custom or standard),
    returning (origin_line, tail_text).
    """
    lines = (tb_text or "").splitlines()
    tail = "\n".join(lines[-35:])

    origin = "unknown"
    # Prefer a frame that includes "/addons/" or "/extra-addons/"
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if "File " in line and ("/addons/" in line or "/extra-addons/" in line or "/odoo/addons/" in line):
            # Typical: File "/path/to/file.py", line 123, in method
            origin = line.strip()
            # include next line which usually contains the code line
            if i + 1 < len(lines):
                origin = origin + "\n" + lines[i + 1].strip()
            break
    return origin, tail


class WebsiteSaleAccessDebug(WebsiteSale):

    @http.route(
        ["/lx/access_debug/product_info"],
        type="json",
        auth="public",
        website=True,
        csrf=False,
    )
    def lx_access_debug_product_info(self, product_id=None, **kw):
        """
        Returns public debug info about access errors, only when debug_access=1 is passed.
        """
        if request.httprequest.args.get("debug_access") != "1":
            return {"ok": False, "error": "debug_access disabled"}

        pid = int(product_id or 0)
        if not pid:
            return {"ok": False, "error": "missing product_id"}

        try:
            # This line may trigger the same error your website hits,
            # because public user has limited access.
            p = request.env["product.template"].browse(pid)
            p.exists()

            # Force-read a few common fields to reproduce render-related access patterns
            p.read(["name", "website_published"])

            return {"ok": True, "product": {"id": p.id, "name": p.name}}

        except AccessError as e:
            tb = traceback.format_exc()
            origin, tail = _extract_origin(tb)
            return {
                "ok": False,
                "kind": "AccessError",
                "message": str(e),
                "origin": origin,
                "trace_tail": tail,
            }
        except Exception as e:
            tb = traceback.format_exc()
            origin, tail = _extract_origin(tb)
            return {
                "ok": False,
                "kind": "Exception",
                "message": str(e),
                "origin": origin,
                "trace_tail": tail,
            }

    @http.route(
        ["/shop/<model('product.template'):product>"],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
    )
    def product(self, product, category="", search="", **kwargs):
        """
        Wrap the standard product page rendering to capture the real render traceback.
        If it fails, store the traceback in session so JS can fetch it.
        """
        try:
            return super().product(product, category=category, search=search, **kwargs)
        except AccessError as e:
            tb = traceback.format_exc()
            request.session["lx_last_access_tb"] = tb
            request.session["lx_last_access_path"] = request.httprequest.path
            raise
        except Exception:
            tb = traceback.format_exc()
            request.session["lx_last_access_tb"] = tb
            request.session["lx_last_access_path"] = request.httprequest.path
            raise

    @http.route(
        ["/lx/access_debug/last"],
        type="json",
        auth="public",
        website=True,
        csrf=False,
    )
    def lx_access_debug_last(self, **kw):
        """
        Returns the last captured traceback from the real product render attempt.
        """
        if request.httprequest.args.get("debug_access") != "1":
            return {"ok": False, "error": "debug_access disabled"}

        tb = request.session.get("lx_last_access_tb") or ""
        path = request.session.get("lx_last_access_path") or ""
        if not tb:
            return {"ok": False, "error": "no traceback captured yet", "path": path}

        origin, tail = _extract_origin(tb)
        return {
            "ok": False,
            "kind": "CapturedTraceback",
            "path": path,
            "origin": origin,
            "trace_tail": tail,
            "trace_full": tb,
        }
