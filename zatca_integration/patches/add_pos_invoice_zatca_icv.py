from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"POS Invoice": [
				{
					"fieldname": "zatca_icv",
					"fieldtype": "Int",
					"label": "ZATCA ICV",
					"insert_after": "zatca_uuid",
					"read_only": 1,
					"no_copy": 1,
					"description": "Invoice Counter Value sent to ZATCA - allocated once from the EGS unit's counter and reused on every retry.",
				},
			]
		}
	)
