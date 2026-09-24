import frappe
from frappe.model.document import Document
from frappe.utils import add_years, get_datetime, now_datetime

from zatca_integration.zatca_integration.utils.engine_client import ZatcaEngineClient, ZatcaEngineError

PCSID_ASSUMED_VALIDITY_YEARS = 5
"""Neither /request-pcsid, /renew-pcsid, nor /credentials return the PCSID's
real expiry - this is ZainZone's stated default, not a value ZATCA itself has
confirmed to this app."""


class ZATCAEGSUnit(Document):
	def validate(self):
		scope = self.transaction_type_scope
		if self.branch and scope not in ("STANDARD", "BOTH"):
			frappe.throw(
				"Branch only applies when Transaction Type is STANDARD or BOTH.", title="Scope Mismatch"
			)
		if self.pos_profile and scope not in ("SIMPLIFIED", "BOTH"):
			frappe.throw(
				"POS Profile only applies when Transaction Type is SIMPLIFIED or BOTH.",
				title="Scope Mismatch",
			)
		if self.pos_profile:
			pos_company = frappe.db.get_value("POS Profile", self.pos_profile, "company")
			if pos_company and pos_company != self.company:
				frappe.throw(
					f"POS Profile {self.pos_profile} belongs to {pos_company}, not {self.company}.",
					title="Scope Mismatch",
				)

	def get_settings(self):
		return frappe.get_doc("ZATCA Settings", self.zatca_settings)

	def deactivate_conflicting_units(self):
		"""Keep exactly one active Production unit per (company, environment,
		transaction_type_scope, pos_profile, branch) - mirrors the same rule
		already enforced on the Oracle POS-source onboarding path
		(pkg_zatca_onboarding.request_pcsid: 'keep exactly one active EGS unit
		per device/environment'). Called right before a newly issued/renewed
		Production CSID is saved as this unit's own is_active=1."""
		frappe.db.sql(
			"""
			update `tabZATCA EGS Unit`
			set is_active = 0
			where company = %(company)s
			  and environment = %(environment)s
			  and transaction_type_scope = %(scope)s
			  and ifnull(pos_profile, '') = %(pos_profile)s
			  and ifnull(branch, '') = %(branch)s
			  and name != %(name)s
			""",
			{
				"company": self.company,
				"environment": self.environment,
				"scope": self.transaction_type_scope,
				"pos_profile": self.pos_profile or "",
				"branch": self.branch or "",
				"name": self.name or "",
			},
		)

	def get_client(self, settings=None) -> ZatcaEngineClient:
		settings = settings or self.get_settings()
		api_key = settings.get_password("api_key", raise_exception=False)
		if not api_key:
			frappe.throw(
				f"ZATCA Settings {settings.name} has no API key yet - run Sign Up there first.",
				title="Not Signed Up",
			)
		return ZatcaEngineClient(api_key)

	def fail(self, message: str):
		"""Persist a Failed status immediately, independent of the request's
		eventual rollback, so a thrown error doesn't also erase the record of
		what went wrong."""
		self.status = "Failed"
		self.compliance_message = message
		self.save()
		frappe.db.commit()

	def start_onboarding(self, otp: str):
		settings = self.get_settings()
		client = self.get_client(settings)

		try:
			response = client.prepare_onboarding(otp, settings.environment)
		except ZatcaEngineError as e:
			self.fail(str(e))
			frappe.throw(str(e), title="ZATCA Onboarding Failed")

		self.stamp_id = response["stamp_id"]
		self.onboarded_on = now_datetime()
		self.status = "CCSID Issued"
		self.compliance_message = response.get("message")
		self.save()

	def run_compliance_checks(self):
		if self.status not in ("CCSID Issued", "Failed") or not self.stamp_id:
			frappe.throw(
				"Compliance checks require a CCSID from a completed onboarding step first.",
				title="Cannot Run Compliance Checks",
			)

		client = self.get_client()

		try:
			response = client.compliance_checks(self.stamp_id)
		except ZatcaEngineError as e:
			self.fail(str(e))
			frappe.throw(str(e), title="ZATCA Compliance Checks Failed")

		# A non-2xx or {"success": false} response already raised above, so
		# reaching here means all sample invoices passed.
		self.compliance_validation_status = "PASS"
		self.compliance_message = response.get("message")
		self.status = "Compliance Passed"
		self.save()

	def request_production_csid(self):
		if self.status != "Compliance Passed":
			frappe.throw(
				"Production CSID can only be requested after compliance checks have passed.",
				title="Cannot Request Production CSID",
			)

		settings = self.get_settings()
		client = self.get_client(settings)

		try:
			response = client.request_pcsid(self.stamp_id)
		except ZatcaEngineError as e:
			self.fail(str(e))
			frappe.throw(str(e), title="ZATCA Production CSID Request Failed")

		self.pcsid_issued_on = now_datetime()
		self.pcsid_expires_on = add_years(self.pcsid_issued_on, PCSID_ASSUMED_VALIDITY_YEARS)
		self.last_renewal_reminder_on = None
		self.compliance_message = response.get("message")
		self.status = "Production"
		self.is_active = 1
		self._apply_credentials(client)
		self.deactivate_conflicting_units()
		self.save()

	def renew_production_csid(self, otp: str):
		"""Rotate the Production CSID via /onboarding/{stamp_id}/renew-pcsid.

		ZATCA authenticates the renewal with the *current* certificate, so this
		only works while that certificate is still valid; once it lapses the
		unit has to go through onboarding again. The engine generates a new key
		pair on every renewal and persists it itself, but this also re-fetches
		it via _apply_credentials() so the locally cached copy stays in sync."""
		if self.status != "Production" or not self.stamp_id:
			frappe.throw(
				"Only a unit with an issued Production CSID can be renewed.",
				title="Cannot Renew Production CSID",
			)

		if self.pcsid_expires_on and get_datetime(self.pcsid_expires_on) < now_datetime():
			frappe.throw(
				f"The Production CSID's assumed expiry ({self.pcsid_expires_on}) has passed. ZATCA "
				"authenticates a renewal with the current certificate, so this unit has to be "
				"onboarded again from scratch instead.",
				title="Production CSID Expired",
			)

		settings = self.get_settings()
		client = self.get_client(settings)

		try:
			response = client.renew_pcsid(self.stamp_id, otp)
		except ZatcaEngineError as e:
			# Deliberately no self.fail() here: the existing credentials are
			# untouched and still working, so marking the unit Failed would
			# throw away a live PCSID over a transient engine error. Let the
			# transaction roll back and leave the unit as it was.
			frappe.log_error(
				title=f"ZATCA: PCSID renewal failed for EGS unit {self.name}",
				message=frappe.get_traceback(),
			)
			# Nothing on this document is dirty yet, so committing here only
			# persists the Error Log - which the throw below would otherwise
			# roll back along with everything else.
			frappe.db.commit()
			frappe.throw(str(e), title="ZATCA Production CSID Renewal Failed")

		self.pcsid_issued_on = now_datetime()
		self.pcsid_expires_on = add_years(self.pcsid_issued_on, PCSID_ASSUMED_VALIDITY_YEARS)
		self.last_renewal_reminder_on = None
		self.compliance_message = response.get("message")
		self.is_active = 1
		self._apply_credentials(client)
		self.deactivate_conflicting_units()
		self.save()

	def _apply_credentials(self, client: ZatcaEngineClient):
		"""Fetch this unit's private key + PCSID (with its secret) from the
		engine's one-time /credentials endpoint and set them on this doc.

		Called right after request_pcsid/renew_pcsid succeed on the engine, so
		invoice signing can read them locally afterwards instead of hitting
		the engine per invoice. Doesn't roll back the already-issued PCSID on
		failure - that already happened on the engine - so this raises with
		guidance to retry via sync_credentials() instead."""
		try:
			credentials = client.get_credentials(self.stamp_id)
		except ZatcaEngineError as e:
			frappe.log_error(
				title=f"ZATCA: credentials sync failed for EGS unit {self.name}",
				message=frappe.get_traceback(),
			)
			frappe.throw(
				f"The Production CSID was issued on the engine, but fetching the signing "
				f"credentials to store locally failed: {e}. Use 'Sync Credentials' on this EGS "
				"unit to retry before signing invoices with it.",
				title="Credentials Sync Failed",
			)

		self.private_key = credentials["private_key"]
		self.pcsid = credentials["pcsid"]
		self.pcsid_secret = credentials["pcsid_secret"]

	def sync_credentials(self):
		"""Manual retry of _apply_credentials, for when the automatic fetch
		right after issuance/renewal failed."""
		if self.status != "Production" or not self.stamp_id:
			frappe.throw(
				"Signing credentials can only be synced for a unit with an issued Production CSID.",
				title="Cannot Sync Credentials",
			)
		self._apply_credentials(self.get_client())
		self.save()

	def get_signing_credentials(self) -> dict:
		"""Local copy of what invoice signing needs - reads this doc, never
		calls the engine."""
		if not self.pcsid:
			frappe.throw(
				f"EGS unit {self.name} has no signing credentials stored yet - run 'Sync "
				"Credentials' on it first.",
				title="No Signing Credentials",
			)
		return {
			"private_key": self.get_password("private_key"),
			"pcsid": self.pcsid,
			"pcsid_secret": self.get_password("pcsid_secret"),
		}


@frappe.whitelist()
def start_onboarding(egs_unit: str, otp: str) -> dict:
	doc = frappe.get_doc("ZATCA EGS Unit", egs_unit)
	doc.check_permission("write")
	doc.start_onboarding(otp)
	return {"status": doc.status}


@frappe.whitelist()
def run_compliance_checks(egs_unit: str) -> dict:
	doc = frappe.get_doc("ZATCA EGS Unit", egs_unit)
	doc.check_permission("write")
	doc.run_compliance_checks()
	return {"status": doc.status, "validation_status": doc.compliance_validation_status}


@frappe.whitelist()
def request_production_csid(egs_unit: str) -> dict:
	doc = frappe.get_doc("ZATCA EGS Unit", egs_unit)
	doc.check_permission("write")
	doc.request_production_csid()
	return {"status": doc.status}


@frappe.whitelist()
def renew_production_csid(egs_unit: str, otp: str) -> dict:
	doc = frappe.get_doc("ZATCA EGS Unit", egs_unit)
	doc.check_permission("write")
	doc.renew_production_csid(otp)
	return {"status": doc.status}


@frappe.whitelist()
def sync_credentials(egs_unit: str) -> dict:
	doc = frappe.get_doc("ZATCA EGS Unit", egs_unit)
	doc.check_permission("write")
	doc.sync_credentials()
	return {"status": doc.status, "has_credentials": bool(doc.pcsid)}
