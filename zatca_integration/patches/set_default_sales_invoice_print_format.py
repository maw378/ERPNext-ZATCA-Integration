from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	"""Saudi tax invoices need the seller/buyer VAT number and national address on every
	print, so make the Saudi Tax Invoice format the default for Sales Invoice."""
	make_property_setter(
		"Sales Invoice", None, "default_print_format", "Saudi Tax Invoice", "Data", for_doctype=True
	)
