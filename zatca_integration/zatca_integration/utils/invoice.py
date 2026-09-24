"""Reports/clears submitted POS and Sales Invoices with ZATCA via the
stateless /zatca/process engine, and persists/logs the result.

Unlike PKG_ZATCA_POS.report_invoice (which reads invoice data back out of
Oracle tables it must already be sitting in), /zatca/process takes a
self-contained invoice JSON built straight from the ERPNext document - no
tenant/branch/session sync into any other database required. Credentials
come from this company's active ZATCA EGS Unit (cached locally - see
zatca_egs_unit.get_signing_credentials, never fetched from the engine here).

Transaction type:
- POS Invoice is always SIMPLIFIED (B2C) and is *reported*.
- Sales Invoice is STANDARD (B2B) when the customer has a VAT number, and is
  then *cleared* (clearance=True); without a VAT number it's SIMPLIFIED and
  reported, same as POS.
"""

import re
import uuid

import frappe
from frappe.utils import cstr, flt, get_datetime
from frappe.utils.file_manager import save_file

from zatca_integration.zatca_integration.utils.zatca_engine import ZATCA_ENGINE_URL, process_invoice

SUPPORTED_DOCTYPES = ("POS Invoice", "Sales Invoice")
SUCCESS_STATUSES = ("REPORTED", "CLEARED")
# What ZATCA Invoice Log's zatca_status Select accepts - anything else the
# engine returns is logged as ERROR (the raw value stays in response_payload).
LOG_STATUSES = ("REPORTED", "CLEARED", "PENDING", "FAILED", "ERROR")

# ERPNext UOM -> ZATCA/UN-CEFACT unit code. Extend as needed; unmapped UOMs
# fall back to PCE (piece) rather than failing the whole report.
UOM_CODE_MAP = {
	"Nos": "PCE",
	"Unit": "PCE",
	"Kg": "KGM",
	"Litre": "LTR",
	"Meter": "MTR",
	"Box": "BX",
	"Carton": "CT",
}


def get_settings_for_company(company: str):
	settings_name = frappe.db.get_value("ZATCA Settings", {"company": company})
	if not settings_name:
		frappe.throw(f"No ZATCA Settings found for company {company}.", title="ZATCA Not Configured")
	return frappe.get_doc("ZATCA Settings", settings_name)


def get_egs_unit_for_invoice(doc):
	"""Picks the ZATCA EGS Unit that should sign this invoice, instead of one
	single company-wide unit for everything. A company can have several
	Production units - e.g. one SIMPLIFIED unit per POS Profile (device) and
	one STANDARD unit per Branch, matching how ZATCA models EGS units as
	per-device/per-branch in the first place. Resolution order:

	  1. a unit scoped to this exact POS Profile / Branch
	  2. a company-wide unit for this transaction type (no POS Profile/Branch set)

	Only STANDARD/SIMPLIFIED are matched exactly; a unit scoped BOTH matches
	either transaction type."""
	settings = get_settings_for_company(doc.company)
	transaction_type = get_transaction_type(doc)
	pos_profile = doc.get("pos_profile") or None
	branch = doc.get("branch") or None

	egs_unit_name = _resolve_egs_unit(doc.company, settings.environment, transaction_type, pos_profile, branch)
	if not egs_unit_name:
		scoped_to = f"POS Profile {pos_profile}" if pos_profile else f"Branch {branch}" if branch else "no POS Profile/Branch"
		frappe.throw(
			f"No active Production ZATCA EGS Unit found for {doc.company} / {settings.environment} / "
			f"{transaction_type} ({scoped_to}), and no company-wide {transaction_type} fallback unit "
			"either. Configure and onboard one - a unit's Transaction Type, POS Profile and Branch "
			"decide which invoices it signs.",
			title="ZATCA Not Onboarded",
		)

	return frappe.get_doc("ZATCA EGS Unit", egs_unit_name), settings


def _resolve_egs_unit(
	company: str, environment: str, transaction_type: str, pos_profile: str | None, branch: str | None
) -> str | None:
	base = "company = %(company)s and environment = %(environment)s and status = 'Production' " \
		"and is_active = 1 and transaction_type_scope in (%(tt)s, 'BOTH')"
	params = {"company": company, "environment": environment, "tt": transaction_type}

	if pos_profile:
		row = frappe.db.sql(
			f"select name from `tabZATCA EGS Unit` where {base} and pos_profile = %(pos_profile)s limit 1",
			{**params, "pos_profile": pos_profile},
		)
		if row:
			return row[0][0]

	if branch:
		row = frappe.db.sql(
			f"select name from `tabZATCA EGS Unit` where {base} and branch = %(branch)s limit 1",
			{**params, "branch": branch},
		)
		if row:
			return row[0][0]

	# Company-wide fallback: a unit for this transaction type with no
	# specific POS Profile/Branch pinned to it.
	row = frappe.db.sql(
		f"select name from `tabZATCA EGS Unit` where {base} "
		"and ifnull(pos_profile, '') = '' and ifnull(branch, '') = '' limit 1",
		params,
	)
	return row[0][0] if row else None


def get_buyer_vat(doc) -> str | None:
	if doc.doctype != "Sales Invoice":
		return None
	return cstr(doc.get("tax_id") or frappe.db.get_value("Customer", doc.customer, "tax_id")).strip() or None


def get_transaction_type(doc) -> str:
	return "STANDARD" if get_buyer_vat(doc) else "SIMPLIFIED"


def allocate_icv(doctype: str, name: str, egs_unit: str) -> int:
	"""The Invoice Counter Value ZATCA requires - the engine takes it from
	invoice.invoice_id and crashes (Cloudflare 502) when that is null. Must
	increase by one per invoice from the same EGS unit - across POS and Sales
	Invoices alike - so it's allocated from the unit's counter under a row
	lock, and persisted on the invoice so retries reuse it instead of burning
	a new number."""
	existing = frappe.db.get_value(doctype, name, "zatca_icv")
	if existing:
		return existing

	last_icv = frappe.db.sql(
		"select last_icv from `tabZATCA EGS Unit` where name = %s for update", egs_unit
	)[0][0]
	icv = (last_icv or 0) + 1
	frappe.db.set_value("ZATCA EGS Unit", egs_unit, "last_icv", icv, update_modified=False)
	frappe.db.set_value(doctype, name, "zatca_icv", icv, update_modified=False)
	# Commit now so the number is never reused, even if the engine call below fails.
	frappe.db.commit()
	return icv


def build_buyer(doc) -> dict:
	"""Buyer party for a STANDARD invoice - same keys the engine uses for
	seller (it maps them onto AccountingCustomerParty the same way)."""
	address = frappe.get_doc("Address", doc.customer_address) if doc.get("customer_address") else None
	country = address.country if address else None
	country_code = cstr(frappe.db.get_value("Country", country, "code") if country else "sa").upper()

	return {
		"name": doc.customer_name,
		"vat_number": get_buyer_vat(doc),
		"street_name": address.address_line1 if address else None,
		"building_number": address.get("zatca_building_number") if address else None,
		"district": (address.get("zatca_district") or address.address_line2) if address else None,
		"city_name": address.city if address else None,
		"postal_zone": address.pincode if address else None,
		"country_code": country_code,
	}


def validate_standard_invoice(doc, method=None):
	"""Sales Invoice before_submit hook - a STANDARD invoice ZATCA will reject
	for missing buyer data (BR-KSA-63 etc.) is caught here, while the user can
	still fix the customer/address, instead of failing silently in the
	background job after submit."""
	if doc.get("is_consolidated") or get_transaction_type(doc) != "STANDARD":
		return

	errors = []
	vat = get_buyer_vat(doc)
	if not re.fullmatch(r"3\d{13}3", vat):
		errors.append(f"Customer VAT number {vat} must be 15 digits, starting and ending with 3.")

	if not doc.get("customer_address"):
		errors.append("Select a Customer Address - ZATCA requires the buyer's address on standard invoices.")
	else:
		buyer = build_buyer(doc)
		if buyer["country_code"] == "SA":
			required = {
				"street_name": "Address Line 1 (street)",
				"building_number": "Building Number",
				"district": "District",
				"city_name": "City",
				"postal_zone": "Postal Code",
			}
			missing = [label for key, label in required.items() if not buyer.get(key)]
			if missing:
				errors.append(f"Address {doc.customer_address} is missing: {', '.join(missing)}.")
			if buyer.get("building_number") and not re.fullmatch(r"\d{4}", cstr(buyer["building_number"])):
				errors.append("Building Number must be exactly 4 digits.")
			if buyer.get("postal_zone") and not re.fullmatch(r"\d{5}", cstr(buyer["postal_zone"])):
				errors.append("Postal Code must be exactly 5 digits.")

	if errors:
		frappe.throw("<br>".join(errors), title="ZATCA: Standard Invoice Buyer Details")


def build_invoice_json(doc, settings, icv: int, transaction_type: str) -> dict:
	"""doc is a submitted POS/Sales Invoice, settings its company's ZATCA
	Settings (the source of seller details - the same data already used at
	Sign Up, rather than re-deriving it from Company/Address)."""
	is_credit_note = bool(doc.is_return)
	is_debit_note = bool(doc.get("is_debit_note"))
	is_standard = transaction_type == "STANDARD"
	posting_dt = get_datetime(f"{doc.posting_date} {doc.posting_time}")

	# Simplification: one flat tax rate for the whole invoice, taken from the
	# invoice's own tax table - matches the common single-VAT-template setup.
	# Per-item mixed tax rates (Item Tax Template overrides) aren't handled yet.
	tax_rate = flt(doc.taxes[0].rate) if doc.taxes else 0.0
	tax_category_code = "S" if tax_rate else "E"

	lines = []
	for idx, item in enumerate(doc.items, start=1):
		line_tax_amount = flt(flt(item.net_amount) * tax_rate / 100, 2)
		lines.append(
			{
				"line_id": idx,
				"item_id": idx,
				"item_name": item.item_name,
				"quantity": item.qty,
				"unit_code": UOM_CODE_MAP.get(item.uom, "PCE"),
				"unit_price": item.rate,
				"line_total": item.amount,
				# item.discount_amount is ERPNext's per-unit discount off the price
				# list rate, and it's already baked into rate/amount above - sending
				# it too makes the engine subtract it a second time (600 at 200/unit
				# off a 500 list price came out as TaxExclusiveAmount 300).
				"discount_amount": 0,
				"tax_category_code": tax_category_code,
				"tax_percent": tax_rate,
				"tax_amount": line_tax_amount,
				"net_total": flt(flt(item.net_amount) + line_tax_amount, 2),
			}
		)

	tax_subtotals = []
	if tax_rate or doc.total_taxes_and_charges:
		tax_subtotals.append(
			{
				"tax_category_code": tax_category_code,
				"tax_percent": tax_rate,
				"taxable_amount": doc.net_total,
				"tax_amount": doc.total_taxes_and_charges,
				"tax_scheme_id": "VAT",
			}
		)

	payments = [
		{"method": (p.mode_of_payment or "CASH").upper(), "amount": p.amount} for p in doc.get("payments") or []
	] or [{"method": "CASH", "amount": doc.grand_total}]

	if is_credit_note:
		document_type, type_code = "CREDIT_NOTE", "381"
	elif is_debit_note:
		document_type, type_code = "DEBIT_NOTE", "383"
	else:
		document_type, type_code = "INVOICE", "388"
	is_note = is_credit_note or is_debit_note

	invoice = {
		# The engine writes this into the XML as the ICV - never None.
		"invoice_id": icv,
		"invoice_number": doc.name,
		"annual_serial": doc.name,
		"uuid": doc.get("zatca_uuid") or str(uuid.uuid4()),
		"invoice_type": "SALE",
		"document_type": document_type,
		"transaction_type": transaction_type,
		"invoice_type_code": type_code,
		"invoice_type_name": "0100000" if is_standard else "0200000",
		"environment": settings.environment,
		"issue_date": posting_dt.strftime("%Y-%m-%d"),
		"issue_time": posting_dt.strftime("%H:%M:%S") + "Z",
		"currency_code": doc.currency,
		"total_amount": doc.total,
		"discount_amount": flt(doc.get("discount_amount")),
		"tax_amount": doc.total_taxes_and_charges,
		"net_amount": doc.grand_total,
		"prepaid_amount": 0,
		"original_invoice_number": doc.return_against if is_note else None,
		"reason": (doc.get("remarks") or ("Sales return" if is_credit_note else "Price adjustment"))
		if is_note
		else None,
		"seller": {
			"name": settings.name_en,
			"vat_number": frappe.db.get_value("Company", doc.company, "tax_id"),
			"company_id": settings.cr_number,
			"street_name": settings.street_name,
			"building_number": settings.building_number,
			"district": settings.district,
			"city_name": settings.city,
			"postal_zone": settings.postal_code,
			"country_code": "SA",
			"email": settings.email,
			"phone": settings.phone_number,
		},
		"lines": lines,
		"tax_subtotals": tax_subtotals,
		"payments": payments,
		"allowances": [],
		"charges": [],
		"extra": {},
	}
	# Buyer is optional for SIMPLIFIED (B2C) per the engine's docs, mandatory for STANDARD.
	if is_standard:
		invoice["buyer"] = build_buyer(doc)

	return invoice


def report_invoice(doctype: str, name: str) -> dict:
	"""The single entry point for reporting/clearing an invoice - called from
	on_invoice_submit below, and safe to call again directly for a manual
	re-report (as opposed to ZATCAInvoiceLog.retry(), which replays the exact
	previous request instead of rebuilding it)."""
	doc = frappe.get_doc(doctype, name)

	# A stable UUID matters to ZATCA - persist it up front so a rebuild on
	# retry reuses the same one rather than generating a new one each time.
	if not doc.get("zatca_uuid"):
		frappe.db.set_value(doctype, name, "zatca_uuid", str(uuid.uuid4()), update_modified=False)
		doc.reload()

	request_url = None
	request_context = None
	response = None

	try:
		egs_unit, settings = get_egs_unit_for_invoice(doc)
		credentials = egs_unit.get_signing_credentials()
		transaction_type = get_transaction_type(doc)
		clearance = transaction_type == "STANDARD"
		icv = allocate_icv(doctype, name, egs_unit.name)

		payload = {
			"invoice_id": icv,
			"invoice": build_invoice_json(doc, settings, icv, transaction_type),
			"credentials": {
				"binary_token": credentials["pcsid"],
				"secret": credentials["pcsid_secret"],
				"private_key_pem": credentials["private_key"],
				"certificate_base64": credentials["pcsid"],
			},
			"submit_to_zatca": True,
			"clearance": clearance,
			"response_format": "json",
		}
		request_context = {"body": payload}
		request_url = ZATCA_ENGINE_URL
		http_status, response = process_invoice(
			payload["invoice"],
			payload["credentials"],
			invoice_id=icv,
			submit_to_zatca=True,
			clearance=clearance,
		)
	except Exception as e:
		frappe.log_error(
			title=f"ZATCA: reporting failed for {doctype} {name}",
			message=frappe.get_traceback(),
		)
		http_status = None
		response = {"status": "error", "code": "REPORT_FAILED", "message": str(e)}

	if response.get("status") == "error" and not response.get("zatca_status"):
		response = {**response, "zatca_status": "ERROR"}

	return persist_zatca_result(
		reference_doctype=doctype,
		reference_name=name,
		response=response,
		request_url=request_url,
		request_context=request_context,
		http_status=http_status,
	)


def on_invoice_submit(doc, method=None):
	"""doc_events hook - enqueued so a slow/unavailable ZATCA engine never
	blocks or fails the actual checkout. enqueue_after_commit ensures this
	only fires once the submit has actually committed."""
	# A POS Closing Entry's consolidated Sales Invoice only re-books POS
	# Invoices that were each already reported - reporting it again would
	# double-report every sale.
	if doc.get("is_consolidated"):
		return

	frappe.enqueue(
		"zatca_integration.zatca_integration.utils.invoice.report_invoice",
		queue="short",
		enqueue_after_commit=True,
		doctype=doc.doctype,
		name=doc.name,
	)


def persist_zatca_result(
	reference_doctype: str,
	reference_name: str,
	response: dict,
	request_url: str | None = None,
	request_context: dict | None = None,
	http_status: int | None = None,
) -> dict:
	"""response is the engine's parsed JSON body (success or failure).

	On success (zatca_status in REPORTED/CLEARED) this attaches the signed
	XML as a private File and records uuid/qr/status/timestamp on the
	invoice. On failure it only records the status there - deliberately
	never touches the XML/QR/UUID fields, so a failed retry can't blank out
	a previously successful report (see the report_invoice review: the
	engine-side procedure has this same bug on the `invoices` table - don't
	repeat it here).

	Every call - success or failure - writes one ZATCA Invoice Log row."""
	zatca_status = response.get("zatca_status")
	frappe.db.set_value(
		reference_doctype, reference_name, "zatca_status", zatca_status, update_modified=False
	)

	xml_file_url = None
	if zatca_status in SUCCESS_STATUSES:
		updates = {
			"zatca_uuid": response.get("uuid"),
			"zatca_reported_at": frappe.utils.now_datetime(),
		}

		qr_base64 = response.get("qr_base64")
		if qr_base64:
			updates["zatca_qr_base64"] = qr_base64

		signed_xml = response.get("signed_xml")
		if signed_xml:
			xml_file_name = response.get("xml_file_name") or f"{reference_name}.xml"
			file_doc = save_file(
				fname=xml_file_name,
				content=signed_xml,
				dt=reference_doctype,
				dn=reference_name,
				is_private=1,
			)
			xml_file_url = file_doc.file_url
			updates["zatca_xml_file"] = xml_file_url

		for fieldname, value in updates.items():
			frappe.db.set_value(reference_doctype, reference_name, fieldname, value, update_modified=False)

	_log_attempt(
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		zatca_status=zatca_status,
		http_status=http_status,
		request_url=request_url,
		request_context=request_context,
		response=response,
	)

	return {"persisted": True, "zatca_status": zatca_status, "xml_file": xml_file_url}


def _log_attempt(
	reference_doctype: str,
	reference_name: str,
	zatca_status: str | None,
	http_status: int | None,
	request_url: str | None,
	request_context: dict | None,
	response: dict,
):
	attempt_no = (
		frappe.db.count(
			"ZATCA Invoice Log",
			filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
		)
		or 0
	) + 1
	body = (request_context or {}).get("body") or {}

	log = frappe.new_doc("ZATCA Invoice Log")
	log.reference_doctype = reference_doctype
	log.reference_name = reference_name
	log.transaction_type = (body.get("invoice") or {}).get("transaction_type")
	log.attempt_no = attempt_no
	log.zatca_status = zatca_status if zatca_status in LOG_STATUSES else "ERROR"
	log.http_status = http_status
	log.reported_at = frappe.utils.now_datetime()
	log.request_url = request_url
	log.request_context = frappe.as_json(request_context) if request_context else None
	log.response_payload = frappe.as_json(response)
	if zatca_status not in SUCCESS_STATUSES:
		log.error_message = response.get("message") or f"Engine returned zatca_status={zatca_status}"
	log.insert(ignore_permissions=True)
	frappe.db.commit()


@frappe.whitelist()
def persist_zatca_result_api(
	reference_name: str,
	response,
	reference_doctype: str = "POS Invoice",
	request_url: str | None = None,
	request_context=None,
	http_status: int | None = None,
) -> dict:
	"""Whitelisted wrapper - call this right after your own engine call
	returns, from wherever that call is made (Client Script, another app, a
	different system entirely). Pass the request_url and request_context
	(headers/body actually sent) you used, so a later Retry on the resulting
	log entry can replay the exact same request."""
	if reference_doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(f"ZATCA reporting isn't supported for {reference_doctype}.")
	frappe.get_doc(reference_doctype, reference_name).check_permission("write")
	if isinstance(response, str):
		response = frappe.parse_json(response)
	if isinstance(request_context, str):
		request_context = frappe.parse_json(request_context)
	return persist_zatca_result(
		reference_doctype, reference_name, response, request_url, request_context, http_status
	)
