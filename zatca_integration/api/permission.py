import frappe


def has_app_permission() -> bool:
	"""Gate the /apps tile on the same permission the app's own doctypes use,
	so the tile doesn't appear for users who can't open anything behind it."""
	return bool(frappe.has_permission("ZATCA Settings", "read"))
