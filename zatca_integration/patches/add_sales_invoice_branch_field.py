from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Sales Invoice has no Branch field out of the box - added so
	utils.invoice.get_egs_unit_for_invoice can route a standard invoice to
	the ZATCA EGS Unit scoped to its branch, the same way pos_profile already
	routes a POS Invoice/consolidated Sales Invoice to its device's unit."""
	create_custom_fields(
		{
			"Sales Invoice": [
				{
					"fieldname": "branch",
					"fieldtype": "Link",
					"label": "Branch",
					"options": "Branch",
					"insert_after": "cost_center",
					"description": "Which ZATCA EGS Unit (if branch-scoped) signs this invoice - see ZATCA EGS Unit.",
				},
			]
		}
	)
