import re

import frappe
from frappe.utils import cstr

from .invoice import get_buyer_vat

ADDRESS_FIELDS = (
	("street", "Street / الشارع"),
	("building_number", "Building No. / رقم المبنى"),
	("district", "District / الحي"),
	("city", "City / المدينة"),
	("postal_code", "Postal Code / الرمز البريدي"),
)


def _address_from_doc(address) -> dict:
	"""Saudi national-address parts from an Address doc (same mapping build_buyer uses)."""
	return {
		"street": cstr(address.address_line1).strip(),
		"building_number": cstr(address.get("zatca_building_number")).strip(),
		"district": cstr(address.get("zatca_district") or address.address_line2).strip(),
		"city": cstr(address.city).strip(),
		"postal_code": cstr(address.pincode).strip(),
		"country": cstr(address.country).strip(),
	}


def _seller_address(doc) -> tuple[dict, str, str]:
	"""Seller national address and names. ZATCA Settings is what the reported XML uses, so
	it wins; the company's own Address is the fallback for companies not set up there."""
	settings_name = frappe.db.get_value("ZATCA Settings", {"company": doc.company})
	if settings_name:
		s = frappe.get_doc("ZATCA Settings", settings_name)
		address = {
			"street": cstr(s.street_name).strip(),
			"building_number": cstr(s.building_number).strip(),
			"district": cstr(s.district).strip(),
			"city": cstr(s.city).strip(),
			"postal_code": cstr(s.postal_code).strip(),
			"additional_number": cstr(s.additional_number).strip(),
			"country": "Saudi Arabia",
		}
		return address, cstr(s.name_en or doc.company), cstr(s.name_ar)

	address_name = doc.get("company_address") or frappe.db.get_value(
		"Address",
		{"is_your_company_address": 1, "name": ["in", _company_address_names(doc.company)]},
	)
	address = _address_from_doc(frappe.get_doc("Address", address_name)) if address_name else {}
	return address, cstr(doc.company), ""


def _company_address_names(company: str) -> list[str]:
	return frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": "Company", "link_name": company},
		pluck="parent",
	) or [""]


def _check_party(label: str, vat: str | None, address: dict, problems: list[str]) -> None:
	if not vat:
		problems.append(f"{label}: VAT number is missing / الرقم الضريبي غير موجود")
	elif not re.fullmatch(r"3\d{13}3", vat):
		problems.append(f"{label}: VAT number {vat} must be 15 digits starting and ending with 3")

	for key, caption in ADDRESS_FIELDS:
		if not address.get(key):
			problems.append(f"{label}: {caption} is missing")
	if address.get("building_number") and not re.fullmatch(r"\d{4}", address["building_number"]):
		problems.append(f"{label}: building number {address['building_number']} must be 4 digits")
	if address.get("postal_code") and not re.fullmatch(r"\d{5}", address["postal_code"]):
		problems.append(f"{label}: postal code {address['postal_code']} must be 5 digits")


def get_invoice_parties(doc) -> dict:
	"""Everything a Saudi tax invoice print needs about seller and buyer, plus a list of
	problems (missing/malformed legal data) the print format shows instead of hiding."""
	seller_address, seller_name, seller_name_ar = _seller_address(doc)
	seller_vat = cstr(frappe.db.get_value("Company", doc.company, "tax_id")).strip()
	seller_cr = cstr(frappe.db.get_value("ZATCA Settings", {"company": doc.company}, "cr_number")).strip()

	buyer_vat = get_buyer_vat(doc)
	is_b2b = bool(buyer_vat)
	buyer_address = {}
	if doc.get("customer_address"):
		buyer_address = _address_from_doc(frappe.get_doc("Address", doc.customer_address))

	problems: list[str] = []
	_check_party("Seller / البائع", seller_vat, seller_address, problems)
	if is_b2b:
		_check_party("Buyer / المشتري", buyer_vat, buyer_address, problems)

	vat_rate = next((t.rate for t in doc.taxes if t.rate), 0) if doc.get("taxes") else 0

	return {
		"seller": {"name": seller_name, "name_ar": seller_name_ar, "vat": seller_vat, "cr": seller_cr, **seller_address},
		"buyer": {"name": doc.customer_name, "vat": buyer_vat, **buyer_address},
		"is_b2b": is_b2b,
		"vat_rate": vat_rate,
		"problems": problems,
	}
