import frappe


def execute():
	"""transaction_type_scope is now a required field on ZATCA EGS Unit.
	Backfill existing rows (none in this app's own dev history, but any other
	install's units) as BOTH - the closest equivalent to the old behaviour,
	where a single active_egs_unit signed every invoice regardless of type -
	and make sure is_active is set so get_egs_unit_for_invoice can find them."""
	if not frappe.db.has_column("ZATCA EGS Unit", "transaction_type_scope"):
		return

	frappe.db.sql(
		"""
		update `tabZATCA EGS Unit`
		set transaction_type_scope = 'BOTH'
		where ifnull(transaction_type_scope, '') = ''
		"""
	)
	frappe.db.sql(
		"""
		update `tabZATCA EGS Unit`
		set is_active = 1
		where status = 'Production' and ifnull(is_active, 0) = 0
		"""
	)
