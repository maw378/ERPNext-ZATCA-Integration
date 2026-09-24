import frappe
from frappe.model.document import Document

from zatca_integration.zatca_integration.utils.engine_client import ZatcaEngineClient, ZatcaEngineError


class ZATCACity(Document):
	pass


@frappe.whitelist()
def sync_cities(country: str = "SA") -> dict:
	"""Refresh ZATCA City from the engine's public /cities lookup (no API key
	needed - it's usable before a company has even signed up). Upserts by
	city_id so re-running it just updates names/codes instead of duplicating."""
	frappe.only_for("System Manager")

	client = ZatcaEngineClient()
	try:
		response = client.list_cities(country)
	except ZatcaEngineError as e:
		frappe.throw(str(e), title="ZATCA City Sync Failed")

	synced = 0
	for city in response.get("cities") or []:
		city_id = city.get("city_id")
		if not city_id:
			continue

		name = str(city_id)
		doc = frappe.get_doc("ZATCA City", name) if frappe.db.exists("ZATCA City", name) else frappe.new_doc("ZATCA City")
		doc.city_id = city_id
		doc.city_name_en = city.get("city_name_en")
		doc.city_name_ar = city.get("city_name_ar")
		doc.zatca_code = city.get("zatca_code")
		doc.region_name = city.get("region_name")
		doc.country_code = country
		doc.save(ignore_permissions=True)
		synced += 1

	frappe.db.commit()
	return {"synced": synced}
