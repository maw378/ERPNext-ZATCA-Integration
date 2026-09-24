frappe.ui.form.on("ZATCA Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Sync Cities"), () => sync_cities(frm));

		if (frm.is_new()) {
			return;
		}

		if (!frm.doc.api_key) {
			frm.add_custom_button(__("Sign Up"), () => sign_up(frm));
		}
	},
});

function sync_cities(frm) {
	frappe.call({
		method: "zatca_integration.zatca_integration.doctype.zatca_city.zatca_city.sync_cities",
		freeze: true,
		freeze_message: __("Syncing cities from the ZATCA onboarding engine..."),
		callback: (r) => {
			frappe.show_alert({
				message: __("Synced {0} cities", [r.message.synced]),
				indicator: "green",
			});
			if (!frm.is_new()) {
				frm.reload_doc();
			}
		},
	});
}

function sign_up(frm) {
	frappe.prompt(
		[
			{
				fieldname: "password",
				fieldtype: "Password",
				label: __("Account Password"),
				reqd: 1,
				description: __(
					"Sets the login password for this subscriber account on the ZATCA onboarding engine. " +
						"Not used again after Sign Up - the API key is what authenticates every later call."
				),
			},
		],
		(values) => {
			frappe.call({
				method: "zatca_integration.zatca_integration.doctype.zatca_settings.zatca_settings.signup",
				args: { zatca_settings: frm.doc.name, password: values.password },
				freeze: true,
				freeze_message: __("Registering with the ZATCA onboarding engine..."),
				callback: () => {
					frappe.show_alert({ message: __("API key issued"), indicator: "green" });
					frm.reload_doc();
				},
			});
		},
		__("Sign Up"),
		__("Submit")
	);
}
