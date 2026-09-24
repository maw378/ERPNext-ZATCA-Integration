from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			# Same ZATCA fields POS Invoice has - utils/invoice.py writes both alike.
			"Sales Invoice": [
				{
					"fieldname": "zatca_section",
					"fieldtype": "Section Break",
					"label": "ZATCA",
					"insert_after": "taxes_and_charges",
					"collapsible": 1,
				},
				{
					"fieldname": "zatca_status",
					"fieldtype": "Select",
					"label": "ZATCA Status",
					"options": "\nREPORTED\nCLEARED\nPENDING\nFAILED\nERROR",
					"insert_after": "zatca_section",
					"read_only": 1,
					"no_copy": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
				},
				{
					"fieldname": "zatca_uuid",
					"fieldtype": "Data",
					"label": "ZATCA UUID",
					"insert_after": "zatca_status",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "zatca_icv",
					"fieldtype": "Int",
					"label": "ZATCA ICV",
					"insert_after": "zatca_uuid",
					"read_only": 1,
					"no_copy": 1,
					"description": "Invoice Counter Value sent to ZATCA - allocated once from the EGS unit's counter and reused on every retry.",
				},
				{
					"fieldname": "zatca_column_break",
					"fieldtype": "Column Break",
					"insert_after": "zatca_icv",
				},
				{
					"fieldname": "zatca_reported_at",
					"fieldtype": "Datetime",
					"label": "Reported At",
					"insert_after": "zatca_column_break",
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "zatca_qr_base64",
					"fieldtype": "Long Text",
					"label": "ZATCA QR (base64)",
					"insert_after": "zatca_reported_at",
					"read_only": 1,
					"no_copy": 1,
					"hidden": 1,
				},
				{
					"fieldname": "zatca_xml_file",
					"fieldtype": "Attach",
					"label": "ZATCA Signed XML",
					"insert_after": "zatca_qr_base64",
					"read_only": 1,
					"no_copy": 1,
				},
			],
			# National-address parts ZATCA requires for a Saudi buyer on standard
			# invoices (BR-KSA-63) that ERPNext's Address has no field for.
			"Address": [
				{
					"fieldname": "zatca_building_number",
					"fieldtype": "Data",
					"label": "Building Number",
					"insert_after": "address_line2",
					"length": 4,
					"description": "4-digit building number from the Saudi national address (ZATCA).",
				},
				{
					"fieldname": "zatca_district",
					"fieldtype": "Data",
					"label": "District",
					"insert_after": "zatca_building_number",
					"description": "District (neighbourhood) for ZATCA - falls back to Address Line 2 when empty.",
				},
			],
		}
	)
