from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Optional direct pin: a POS Profile can name exactly which ZATCA EGS
	Unit signs its invoices. Left blank, utils.invoice.get_egs_unit_for_invoice
	falls back to scope-matched/company-wide/any-active resolution instead -
	this is an override, not a requirement."""
	create_custom_fields(
		{
			"POS Profile": [
				{
					"fieldname": "zatca_egs_unit",
					"fieldtype": "Link",
					"label": "ZATCA EGS Unit",
					"options": "ZATCA EGS Unit",
					"insert_after": "company",
					"description": (
						"Optional. Pin this terminal to one specific ZATCA EGS Unit. "
						"Leave blank to let ZATCA reporting use any available active "
						"Production unit for this company instead."
					),
				},
			]
		}
	)
