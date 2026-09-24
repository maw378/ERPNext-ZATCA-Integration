frappe.listview_settings["ZATCA City"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Sync Cities"), () => {
			frappe.call({
				method: "zatca_integration.zatca_integration.doctype.zatca_city.zatca_city.sync_cities",
				freeze: true,
				freeze_message: __("Syncing cities from the ZATCA onboarding engine..."),
				callback: (r) => {
					frappe.show_alert({
						message: __("Synced {0} cities", [r.message.synced]),
						indicator: "green",
					});
					listview.refresh();
				},
			});
		});
	},
};
