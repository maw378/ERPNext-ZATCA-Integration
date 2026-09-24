import frappe


def execute():
	"""ZATCA Invoice Log used to link only to POS Invoice (pos_invoice); it now
	links to either POS or Sales Invoice via reference_doctype/reference_name.
	Frappe keeps the dropped pos_invoice column, so copy it across."""
	if not frappe.db.has_column("ZATCA Invoice Log", "pos_invoice"):
		return

	frappe.db.sql(
		"""
		update `tabZATCA Invoice Log`
		set reference_doctype = 'POS Invoice', reference_name = pos_invoice
		where ifnull(reference_name, '') = '' and ifnull(pos_invoice, '') != ''
		"""
	)
	frappe.db.sql(
		"""
		update `tabZATCA Invoice Log`
		set transaction_type = 'SIMPLIFIED'
		where reference_doctype = 'POS Invoice' and ifnull(transaction_type, '') = ''
		"""
	)
