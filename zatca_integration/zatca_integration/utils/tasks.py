"""Scheduled tasks for the ZATCA integration.

Renewal is deliberately *not* automated: /onboarding/{stamp_id}/renew-pcsid
needs a fresh Fatoora OTP that only a human can fetch from the portal. What we
can automate is the reminder, early enough that someone still has time to act
- a PCSID can only be renewed while it is still valid, so a lapsed certificate
means redoing the whole onboarding (CCSID -> compliance checks -> PCSID)
instead.

pcsid_expires_on itself is not read from ZATCA - the onboarding engine never
hands back the PCSID certificate, so this app has no way to read its real
expiry. It defaults to 5 years after issuance/renewal (see
PCSID_ASSUMED_VALIDITY_YEARS in the ZATCA EGS Unit controller), a figure from
ZainZone rather than one ZATCA has confirmed to this app.
"""

import frappe
from frappe.utils import add_days, date_diff, getdate, nowdate

DEFAULT_REMINDER_DAYS = 30
REMINDER_INTERVAL_DAYS = 7


def check_pcsid_expiry():
	units = frappe.get_all(
		"ZATCA EGS Unit",
		filters={"status": "Production", "pcsid_expires_on": ["is", "set"]},
		fields=[
			"name",
			"company",
			"environment",
			"zatca_settings",
			"pcsid_expires_on",
			"last_renewal_reminder_on",
		],
	)

	for unit in units:
		reminder_days = (
			frappe.db.get_value("ZATCA Settings", unit.zatca_settings, "pcsid_renewal_reminder_days")
			or DEFAULT_REMINDER_DAYS
		)
		days_left = date_diff(getdate(unit.pcsid_expires_on), getdate(nowdate()))

		if days_left > reminder_days:
			continue

		if unit.last_renewal_reminder_on and getdate(unit.last_renewal_reminder_on) > getdate(
			add_days(nowdate(), -REMINDER_INTERVAL_DAYS)
		):
			continue

		notify_pcsid_expiry(unit, days_left)
		frappe.db.set_value("ZATCA EGS Unit", unit.name, "last_renewal_reminder_on", nowdate())

	frappe.db.commit()


def notify_pcsid_expiry(unit, days_left: int):
	if days_left < 0:
		subject = f"ZATCA PCSID for {unit.company} expired {abs(days_left)} day(s) ago"
		body = (
			f"The Production CSID on EGS unit {unit.name} ({unit.environment}) expired on "
			f"{unit.pcsid_expires_on}. ZATCA authenticates a renewal with the current certificate, "
			"so renewal is no longer possible - this unit has to be onboarded again from scratch."
		)
	else:
		subject = f"ZATCA PCSID for {unit.company} expires in {days_left} day(s)"
		body = (
			f"The Production CSID on EGS unit {unit.name} ({unit.environment}) expires on "
			f"{unit.pcsid_expires_on}. Open the EGS unit, click Renew Production CSID, and supply a "
			"fresh Fatoora OTP before that date - after it, renewal is no longer possible and the "
			"unit has to be onboarded again."
		)

	recipients = get_notification_recipients(unit)
	if not recipients:
		return

	for user in recipients:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": subject,
				"email_content": body,
				"for_user": user,
				"type": "Alert",
				"document_type": "ZATCA EGS Unit",
				"document_name": unit.name,
			}
		).insert(ignore_permissions=True)

	frappe.sendmail(recipients=recipients, subject=subject, message=body, now=False)


def get_notification_recipients(unit) -> list[str]:
	users = frappe.get_all(
		"Has Role",
		filters={"role": "System Manager", "parenttype": "User"},
		pluck="parent",
	)

	enabled = frappe.get_all(
		"User",
		filters={"name": ["in", users], "enabled": 1},
		pluck="name",
	)

	return [u for u in enabled if u not in ("Administrator", "Guest")]
