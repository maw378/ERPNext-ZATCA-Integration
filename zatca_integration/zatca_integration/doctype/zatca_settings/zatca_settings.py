import frappe
from frappe.model.document import Document
from frappe.utils import cint

from zatca_integration.zatca_integration.utils.engine_client import ZatcaEngineClient, ZatcaEngineError


class ZATCASettings(Document):
	def get_client(self) -> ZatcaEngineClient:
		return ZatcaEngineClient(self.get_password("api_key", raise_exception=False))

	def signup(self, password: str):
		"""Register this company with the onboarding engine and store its API key.

		One-shot: the engine has no update-subscriber endpoint, so re-running
		this after an API key is already stored would just create a duplicate
		subscriber record for the same VAT number."""
		if self.get_password("api_key", raise_exception=False):
			frappe.throw(
				"This company already has an API key. Contact ZainZone if it needs to be reissued.",
				title="Already Signed Up",
			)

		vat_number = frappe.get_cached_value("Company", self.company, "tax_id")
		if not vat_number:
			frappe.throw(
				f"Company {self.company} has no Tax ID set - the engine needs it as the VAT number.",
				title="Missing VAT Number",
			)

		payload = {
			"vat_number": vat_number,
			"cr_number": self.cr_number,
			"email": self.email,
			"password": password,
			"name_ar": self.name_ar,
			"name_en": self.name_en,
			"building_no": self.building_number,
			"street_name": self.street_name,
			"district": self.district,
			"city": self.city,
			"postal_code": self.postal_code,
			"additional_number": self.additional_number,
			"phone_number": self.phone_number,
			# city_id is a Link to ZATCA City now - its name is the numeric id
			# as text (autoname: field:city_id), cast back to a number for the
			# engine's JSON contract.
			"city_id": cint(self.city_id),
		}

		client = ZatcaEngineClient()
		try:
			response = client.signup(payload)
		except ZatcaEngineError as e:
			frappe.throw(str(e), title="ZATCA Sign Up Failed")

		self.api_key = response["data"]["api_key"]
		self.save()


@frappe.whitelist()
def signup(zatca_settings: str, password: str) -> dict:
	doc = frappe.get_doc("ZATCA Settings", zatca_settings)
	doc.check_permission("write")
	doc.signup(password)
	return {"api_key_set": bool(doc.get_password("api_key", raise_exception=False))}
