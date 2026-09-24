"""Thin HTTP client for the ZATCA invoice-processing engine (/zatca/process).

Unlike the ORDS onboarding API, this one is stateless: it takes a
self-contained invoice + credentials and signs/submits it in one call -
no tenant/branch/session data needs to exist anywhere first. Credentials
come from ZATCA EGS Unit's locally-cached private_key/pcsid/pcsid_secret
(see zatca_egs_unit.get_signing_credentials), not from this engine.
"""

import requests

ZATCA_ENGINE_URL = "https://zatca.zainzone.net/zatca/process"


def process_invoice(
	invoice: dict,
	credentials: dict,
	*,
	invoice_id: int | None = None,
	submit_to_zatca: bool = True,
	clearance: bool = False,
	timeout: int = 60,
) -> tuple[int, dict]:
	"""Returns (http_status, parsed_body). Never raises for a well-formed
	error response - the engine returns HTTP 502 with a JSON error body on
	failure (status/code/message), which the caller inspects same as
	success. Only raises for genuine network failures or a non-JSON body."""
	payload = {
		"invoice_id": invoice_id,
		"invoice": invoice,
		"credentials": credentials,
		"submit_to_zatca": submit_to_zatca,
		"clearance": clearance,
		"response_format": "json",
	}

	response = requests.post(ZATCA_ENGINE_URL, json=payload, timeout=timeout)

	try:
		body = response.json()
	except ValueError as e:
		raise ValueError(
			f"ZATCA processing engine returned a non-JSON response (HTTP {response.status_code}): "
			f"{response.text[:300]}"
		) from e

	return response.status_code, body
