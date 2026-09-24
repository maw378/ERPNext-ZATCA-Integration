"""Renders the ZATCA QR for a receipt print format.

ZATCA's own convention for a simplified tax invoice QR is that the base64
string in the invoice (the TLV-encoded seller/VAT/timestamp/totals/hash
payload) is itself what a scanner reads - the printed barcode's scannable
content is that base64 string as-is, not something decoded further first.
This just QR-encodes it and hands back a data: URI an <img> tag can use
directly, so a print format never needs its own QR library.
"""

import base64
import io

import frappe
import qrcode


@frappe.whitelist()
def render_zatca_qr(qr_base64: str) -> str:
	if not qr_base64:
		return ""

	img = qrcode.make(qr_base64)
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
