frappe.listview_settings["ZATCA Invoice Log"] = {
	get_indicator(doc) {
		const colors = {
			REPORTED: "green",
			CLEARED: "green",
			PENDING: "orange",
			FAILED: "red",
			ERROR: "red",
		};
		return [__(doc.zatca_status), colors[doc.zatca_status] || "gray", `zatca_status,=,${doc.zatca_status}`];
	},
};
