import frappe
import requests
from frappe.model.document import Document

REQUEST_TIMEOUT = 60


class ZATCAInvoiceLog(Document):
	def retry(self) -> dict:
		"""Replays exactly what was sent on this attempt - same URL, same
		headers, same body - so retrying never depends on knowing how or
		where the original call was built."""
		if self.zatca_status in ("REPORTED", "CLEARED"):
			frappe.throw(
				"This attempt already succeeded - nothing to retry.", title="Already Reported"
			)

		if not self.request_url:
			frappe.throw(
				"This log entry has no request URL recorded, so it can't be replayed.",
				title="Cannot Retry",
			)

		context = frappe.parse_json(self.request_context) if self.request_context else {}
		headers = context.get("headers") or {}
		body = context.get("body")

		from zatca_integration.zatca_integration.utils.invoice import (
			persist_zatca_result,
			report_invoice,
		)

		# Attempts logged before the ICV fix carry invoice.invoice_id = null,
		# which always crashes the engine - replaying them can never succeed,
		# so rebuild the request (allocating an ICV) instead.
		if body and not (body.get("invoice") or {}).get("invoice_id"):
			return report_invoice(self.reference_doctype, self.reference_name)

		# Failures are logged as a new attempt (same as the submit-time call)
		# rather than only shown in a popup, so the log list stays the full history.
		http_status = None
		try:
			response = requests.post(
				self.request_url, headers=headers, json=body, timeout=REQUEST_TIMEOUT
			)
			http_status = response.status_code
			payload = response.json()
		except requests.RequestException as e:
			payload = {"status": "error", "code": "ENGINE_UNREACHABLE", "message": str(e)}
		except ValueError:
			payload = {
				"status": "error",
				"code": "NON_JSON_RESPONSE",
				"message": f"ZATCA engine returned a non-JSON response (HTTP {http_status}): "
				f"{response.text[:300]}",
			}

		if payload.get("status") == "error" and not payload.get("zatca_status"):
			payload = {**payload, "zatca_status": "ERROR"}

		return persist_zatca_result(
			reference_doctype=self.reference_doctype,
			reference_name=self.reference_name,
			response=payload,
			request_url=self.request_url,
			request_context=context,
			http_status=http_status,
		)


@frappe.whitelist()
def retry(zatca_invoice_log: str) -> dict:
	doc = frappe.get_doc("ZATCA Invoice Log", zatca_invoice_log)
	doc.check_permission("write")
	return doc.retry()
