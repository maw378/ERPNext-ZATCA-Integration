frappe.ui.form.on("ZATCA EGS Unit", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.status === "Draft" || (frm.doc.status === "Failed" && !frm.doc.stamp_id)) {
			frm.add_custom_button(__("Start Onboarding"), () => start_onboarding(frm));
		}

		if (
			frm.doc.status === "CCSID Issued" ||
			(frm.doc.status === "Failed" && frm.doc.stamp_id)
		) {
			frm.add_custom_button(__("Run Compliance Checks"), () => run_compliance_checks(frm));
		}

		if (frm.doc.status === "Compliance Passed") {
			frm.add_custom_button(__("Request Production CSID"), () => request_production_csid(frm));
		}

		if (frm.doc.status === "Production") {
			frm.add_custom_button(__("Renew Production CSID"), () => renew_production_csid(frm));
			if (!frm.doc.pcsid) {
				frm.add_custom_button(__("Sync Credentials"), () => sync_credentials(frm));
			}
			show_expiry_indicator(frm);
		}
	},
});

function show_expiry_indicator(frm) {
	if (!frm.doc.pcsid_expires_on) {
		return;
	}

	const days_left = moment(frm.doc.pcsid_expires_on).diff(moment(), "days");

	if (days_left < 0) {
		const expired = __(
			"Production CSID's assumed expiry passed {0} day(s) ago. Renewal is no longer possible — this unit must be onboarded again.",
			[Math.abs(days_left)]
		);
		frm.dashboard.set_headline_alert(expired, "red");
	} else if (days_left <= 30) {
		const expiring = __(
			"Production CSID's assumed expiry is in {0} day(s). Renew it before then — ZATCA authenticates the renewal with the current certificate.",
			[days_left]
		);
		frm.dashboard.set_headline_alert(expiring, "orange");
	}
}

function prompt_for_otp(frm, { title, method, freeze_message, success_message }) {
	frappe.prompt(
		[
			{
				fieldname: "otp",
				fieldtype: "Data",
				label: __("Fatoora OTP"),
				reqd: 1,
				description: __("One-time password generated from the Fatoora portal for this EGS unit."),
			},
		],
		(values) => {
			frappe.call({
				method: method,
				args: { egs_unit: frm.doc.name, otp: values.otp },
				freeze: true,
				freeze_message: freeze_message,
				callback: () => {
					frappe.show_alert({ message: success_message, indicator: "green" });
					frm.reload_doc();
				},
			});
		},
		title,
		__("Submit")
	);
}

function start_onboarding(frm) {
	prompt_for_otp(frm, {
		title: __("Start Onboarding"),
		method: "zatca_integration.zatca_integration.doctype.zatca_egs_unit.zatca_egs_unit.start_onboarding",
		freeze_message: __("Onboarding with ZATCA..."),
		success_message: __("CCSID issued"),
	});
}

function sync_credentials(frm) {
	frappe.call({
		method: "zatca_integration.zatca_integration.doctype.zatca_egs_unit.zatca_egs_unit.sync_credentials",
		args: { egs_unit: frm.doc.name },
		freeze: true,
		freeze_message: __("Syncing signing credentials from the engine..."),
		callback: () => {
			frappe.show_alert({ message: __("Signing credentials synced"), indicator: "green" });
			frm.reload_doc();
		},
	});
}

function renew_production_csid(frm) {
	const warning = __(
		"Renewal generates a new key pair and replaces the stored credentials on the engine " +
			"and the local copy on this unit. The current certificate is retired. Continue?"
	);

	frappe.confirm(warning, () => {
		prompt_for_otp(frm, {
			title: __("Renew Production CSID"),
			method: "zatca_integration.zatca_integration.doctype.zatca_egs_unit.zatca_egs_unit.renew_production_csid",
			freeze_message: __("Renewing production CSID..."),
			success_message: __("Production CSID renewed"),
		});
	});
}

function run_compliance_checks(frm) {
	frappe.call({
		method: "zatca_integration.zatca_integration.doctype.zatca_egs_unit.zatca_egs_unit.run_compliance_checks",
		args: { egs_unit: frm.doc.name },
		freeze: true,
		freeze_message: __("Running ZATCA compliance checks..."),
		callback: () => {
			frappe.show_alert({ message: __("Compliance checks passed"), indicator: "green" });
			frm.reload_doc();
		},
	});
}

function request_production_csid(frm) {
	frappe.call({
		method: "zatca_integration.zatca_integration.doctype.zatca_egs_unit.zatca_egs_unit.request_production_csid",
		args: { egs_unit: frm.doc.name },
		freeze: true,
		freeze_message: __("Requesting production CSID..."),
		callback: () => {
			frappe.show_alert({ message: __("Production CSID issued"), indicator: "green" });
			frm.reload_doc();
		},
	});
}
