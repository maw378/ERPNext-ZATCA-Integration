frappe.listview_settings["ZATCA EGS Unit"] = {
	get_indicator(doc) {
		const colors = {
			Draft: "orange",
			"CCSID Issued": "orange",
			"Compliance Passed": "orange",
			Production: "green",
			Failed: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
