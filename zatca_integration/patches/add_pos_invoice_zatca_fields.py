import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"POS Invoice": [
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
					"options": "\nREPORTED\nCLEARED\nFAILED\nERROR",
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
					"fieldname": "zatca_column_break",
					"fieldtype": "Column Break",
					"insert_after": "zatca_uuid",
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
					"description": "Raw base64 TLV payload from the engine - rendered into a scannable QR image on the receipt print format, not meant to be viewed directly.",
				},
				{
					"fieldname": "zatca_xml_file",
					"fieldtype": "Attach",
					"label": "ZATCA Signed XML",
					"insert_after": "zatca_qr_base64",
					"read_only": 1,
					"no_copy": 1,
				},
			]
		}
	)
