frappe.ui.form.on("ZATCA Invoice Log", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (!["REPORTED", "CLEARED"].includes(frm.doc.zatca_status)) {
			frm.add_custom_button(__("Retry"), () => retry(frm));
		}
	},
});

function retry(frm) {
	frappe.confirm(
		__("Resend this exact request to ZATCA for {0} {1}?", [frm.doc.reference_doctype, frm.doc.reference_name]),
		() => {
			frappe.call({
				method: "zatca_integration.zatca_integration.doctype.zatca_invoice_log.zatca_invoice_log.retry",
				args: { zatca_invoice_log: frm.doc.name },
				freeze: true,
				freeze_message: __("Retrying ZATCA submission..."),
				callback: (r) => {
					const success = ["REPORTED", "CLEARED"].includes(r.message.zatca_status);
					frappe.show_alert({
						message: success
							? __("{0} successfully", [r.message.zatca_status === "CLEARED" ? __("Cleared") : __("Reported")])
							: __("Still failed: {0}", [r.message.zatca_status]),
						indicator: success ? "green" : "red",
					});
					frappe.set_route("List", "ZATCA Invoice Log", {
						reference_doctype: frm.doc.reference_doctype,
						reference_name: frm.doc.reference_name,
					});
				},
			});
		}
	);
}
