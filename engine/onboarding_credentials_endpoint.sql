-- ORDS REST module: engine.onboarding  (base path: /engine-api/v1/)
--
-- New template + GET handler for /onboarding/:stamp_id/credentials - the
-- one-time credentials fetch that zatca_integration.utils.engine_client
-- .get_credentials(stamp_id) calls, exactly once, right after
-- /request-pcsid or /renew-pcsid succeeds (see ZATCAEGSUnit._apply_credentials
-- in the ERPNext app). It is NOT meant to be called per invoice.
--
-- v2: the first version compared :api_key directly against
-- DIGITAL_STAMPS.ENGINE_API_KEY, which was wrong - that column isn't the
-- subscriber's auth key (ENGINE_USERS only stores API_KEY_HASH, never the
-- plaintext key, and the ENGINE_API_KEY value on a real row turned out to be
-- independently-generated garbage anyway). This version authenticates the
-- same way the working /request-pcsid handler does: resolve the header to a
-- vat_number via pkg_engine_auth.resolve_vat_from_key, then confirm
-- ownership via pkg_engine_auth.assert_stamp_owned_by, before ever touching
-- DIGITAL_STAMPS directly.
--
-- Still true from the DIGITAL_STAMPS DDL:
--   * only stamps with ONBOARDING_STATUS in ('PCSID_ISSUED', 'READY') and
--     STAMP_STATUS = 'ACTIVE' have a usable Production CSID
--   * the fields returned are PRIVATE_KEY, PRODUCTION_CSID_TOKEN (-> "pcsid")
--     and PRODUCTION_CSID_SECRET (-> "pcsid_secret")
--
-- Separately worth checking on the engine side: the raw values that come
-- back here for private_key/pcsid/pcsid_secret should be sanity-checked for
-- the same duplicated-token corruption seen in ENGINE_USERS' api_key and
-- DIGITAL_STAMPS.ENGINE_API_KEY (both looked like a short token
-- concatenated with itself, off by one digit, suggesting whatever generates
-- these appends across a retry loop instead of overwriting). If
-- pkg_engine_auth.generate_api_key (or whatever writes these secret/token
-- columns) shares that bug, it needs fixing at the source before any of
-- this is safe to sign invoices with.

BEGIN
  ORDS.DEFINE_TEMPLATE(
    p_module_name => 'engine.onboarding',
    p_pattern     => 'onboarding/:stamp_id/credentials'
  );

  ORDS.DEFINE_PARAMETER(
    p_module_name        => 'engine.onboarding',
    p_pattern             => 'onboarding/:stamp_id/credentials',
    p_method              => 'GET',
    p_name                => 'API-KEY',
    p_bind_variable_name  => 'api_key',
    p_source_type         => 'HEADER',
    p_param_type          => 'STRING',
    p_access_method       => 'IN'
  );

  ORDS.DEFINE_HANDLER(
    p_module_name    => 'engine.onboarding',
    p_pattern         => 'onboarding/:stamp_id/credentials',
    p_method          => 'GET',
    p_source_type     => ORDS.source_type_plsql,
    p_items_per_page  => 0,
    p_source          => q'~
DECLARE
  l_vat_number        engine_users.vat_number%TYPE;
  v_stamp_id          digital_stamps.stamp_id%TYPE;
  v_onboarding_status digital_stamps.onboarding_status%TYPE;
  v_stamp_status      digital_stamps.stamp_status%TYPE;
  v_private_key       digital_stamps.private_key%TYPE;
  v_pcsid              digital_stamps.production_csid_token%TYPE;
  v_pcsid_secret       digital_stamps.production_csid_secret%TYPE;
BEGIN
  -- Same auth pattern as the working /request-pcsid handler: resolve the
  -- header to a vat_number, then confirm that vat_number owns this stamp -
  -- never touch DIGITAL_STAMPS.ENGINE_API_KEY for this.
  BEGIN
    l_vat_number := pkg_engine_auth.resolve_vat_from_key(:api_key);
  EXCEPTION
    WHEN OTHERS THEN
      -- TEMPORARY DEBUG: echoes back what this handler actually received.
      -- Revert to the plain "Invalid or missing API key." message once the
      -- 401 is diagnosed - this leaks the key value into the response/logs.
      :status_code := 401;
      APEX_JSON.open_object;
      APEX_JSON.write('success', FALSE);
      APEX_JSON.write('code', 'UNAUTHORIZED');
      APEX_JSON.write('message', 'debug_key=[' || :api_key || '] debug_len=[' ||
        LENGTH(:api_key) || '] debug_err=[' || SQLERRM || ']');
      APEX_JSON.close_object;
      RETURN;
  END;

  BEGIN
    v_stamp_id := TO_NUMBER(:stamp_id);
  EXCEPTION
    WHEN VALUE_ERROR THEN
      :status_code := 400;
      APEX_JSON.open_object;
      APEX_JSON.write('success', FALSE);
      APEX_JSON.write('code', 'INVALID_STAMP_ID');
      APEX_JSON.write('message', 'stamp_id must be numeric.');
      APEX_JSON.close_object;
      RETURN;
  END;

  BEGIN
    pkg_engine_auth.assert_stamp_owned_by(:stamp_id, l_vat_number);
  EXCEPTION
    WHEN OTHERS THEN
      :status_code := 403;
      APEX_JSON.open_object;
      APEX_JSON.write('success', FALSE);
      APEX_JSON.write('code', 'FORBIDDEN');
      APEX_JSON.write('message', 'This API key does not own the given stamp.');
      APEX_JSON.close_object;
      RETURN;
  END;

  BEGIN
    SELECT onboarding_status, stamp_status, private_key,
           production_csid_token, production_csid_secret
      INTO v_onboarding_status, v_stamp_status, v_private_key,
           v_pcsid, v_pcsid_secret
      FROM digital_stamps
     WHERE stamp_id = v_stamp_id;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      :status_code := 404;
      APEX_JSON.open_object;
      APEX_JSON.write('success', FALSE);
      APEX_JSON.write('code', 'NOT_FOUND');
      APEX_JSON.write('message', 'No digital stamp found for this stamp_id.');
      APEX_JSON.close_object;
      RETURN;
  END;

  IF v_stamp_status != 'ACTIVE' THEN
    :status_code := 403;
    APEX_JSON.open_object;
    APEX_JSON.write('success', FALSE);
    APEX_JSON.write('code', 'STAMP_SUSPENDED');
    APEX_JSON.write('message', 'This digital stamp is suspended.');
    APEX_JSON.close_object;
    RETURN;
  END IF;

  IF v_onboarding_status NOT IN ('PCSID_ISSUED', 'READY') THEN
    :status_code := 409;
    APEX_JSON.open_object;
    APEX_JSON.write('success', FALSE);
    APEX_JSON.write('code', 'PCSID_NOT_ISSUED');
    APEX_JSON.write('message', 'No Production CSID has been issued for this stamp yet.');
    APEX_JSON.close_object;
    RETURN;
  END IF;

  IF v_private_key IS NULL OR v_pcsid IS NULL OR v_pcsid_secret IS NULL THEN
    :status_code := 500;
    APEX_JSON.open_object;
    APEX_JSON.write('success', FALSE);
    APEX_JSON.write('code', 'CREDENTIALS_INCOMPLETE');
    APEX_JSON.write('message', 'Stamp is marked ready but one or more credential fields is missing.');
    APEX_JSON.close_object;
    RETURN;
  END IF;

  UPDATE digital_stamps
     SET last_used_at = SYSTIMESTAMP
   WHERE stamp_id = v_stamp_id;
  COMMIT;

  :status_code := 200;
  APEX_JSON.open_object;
  APEX_JSON.write('success', TRUE);
  APEX_JSON.write('code', 'OK');
  APEX_JSON.write('message', 'Signing credentials retrieved.');
  APEX_JSON.write('private_key', v_private_key);
  APEX_JSON.write('pcsid', v_pcsid);
  APEX_JSON.write('pcsid_secret', v_pcsid_secret);
  APEX_JSON.close_object;
END;
~'
  );

  COMMIT;
END;
/
