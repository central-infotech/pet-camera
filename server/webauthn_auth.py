"""WebAuthn (FIDO2) passkey registration and authentication."""

import json
import logging
import os

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes, options_to_json

from . import config

logger = logging.getLogger(__name__)

# Credential storage file
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_CRED_FILE = os.path.join(_DATA_DIR, "webauthn_credentials.json")

# In-memory challenge store: {challenge_b64: bytes}
_pending_challenges: dict[str, bytes] = {}


def _get_rp_id() -> str:
    """Get Relying Party ID from environment or derive from cert files."""
    rp_id = os.environ.get("PET_CAMERA_RP_ID", "")
    if rp_id:
        return rp_id
    # Try to derive from cert file name
    import glob
    certs = glob.glob(os.path.join(config.CERT_DIR, "*.crt"))
    if certs:
        name = os.path.basename(certs[0])
        return name.rsplit(".crt", 1)[0]
    return "localhost"


def _get_rp_name() -> str:
    return "Pet Camera"


def _load_credentials() -> list[dict]:
    if not os.path.isfile(_CRED_FILE):
        return []
    try:
        with open(_CRED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_credentials(creds: list[dict]):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_CRED_FILE, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2, ensure_ascii=False)


def get_credential_count() -> int:
    return len(_load_credentials())


def get_registration_options_json() -> str:
    """Generate registration options and return as JSON string."""
    rp_id = _get_rp_id()
    creds = _load_credentials()

    exclude = []
    for c in creds:
        exclude.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"])))

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=_get_rp_name(),
        user_id=b"pet-camera-user",
        user_name="pet-camera-owner",
        user_display_name="Pet Camera Owner",
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )

    # Store challenge for later verification
    challenge_b64 = bytes_to_base64url(options.challenge)
    _pending_challenges[challenge_b64] = options.challenge

    return options_to_json(options)


def verify_registration(body: dict) -> tuple[bool, str]:
    """Verify registration response. Returns (success, message)."""
    rp_id = _get_rp_id()
    challenge = _find_and_consume_challenge(body)
    if challenge is None:
        return False, "Challenge not found or expired"

    try:
        verification = verify_registration_response(
            credential=body,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=_get_expected_origins(),
        )
    except Exception as e:
        logger.warning("WebAuthn registration verification failed: %s", e)
        return False, str(e)

    # Save credential
    creds = _load_credentials()
    creds.append({
        "credential_id": bytes_to_base64url(verification.credential_id),
        "public_key": bytes_to_base64url(verification.credential_public_key),
        "sign_count": verification.sign_count,
        "name": body.get("name", f"Device {len(creds) + 1}"),
    })
    _save_credentials(creds)
    logger.info("WebAuthn: credential registered (total=%d)", len(creds))
    return True, "ok"


def get_authentication_options_json() -> str:
    """Generate authentication options and return as JSON string."""
    rp_id = _get_rp_id()
    creds = _load_credentials()

    if not creds:
        return ""

    allow = []
    for c in creds:
        allow.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["credential_id"])))

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    challenge_b64 = bytes_to_base64url(options.challenge)
    _pending_challenges[challenge_b64] = options.challenge

    return options_to_json(options)


def verify_authentication(body: dict) -> tuple[bool, str]:
    """Verify authentication response. Returns (success, message)."""
    rp_id = _get_rp_id()
    creds = _load_credentials()

    # Find matching credential
    raw_id_b64 = body.get("rawId", body.get("id", ""))
    matched = None
    matched_idx = -1
    for i, c in enumerate(creds):
        if c["credential_id"] == raw_id_b64:
            matched = c
            matched_idx = i
            break

    if not matched:
        return False, "Unknown credential"

    challenge = _find_and_consume_challenge(body)
    if challenge is None:
        return False, "Challenge not found or expired"

    try:
        verification = verify_authentication_response(
            credential=body,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=_get_expected_origins(),
            credential_public_key=base64url_to_bytes(matched["public_key"]),
            credential_current_sign_count=matched["sign_count"],
        )
    except Exception as e:
        logger.warning("WebAuthn authentication verification failed: %s", e)
        return False, str(e)

    # Update sign count
    creds[matched_idx]["sign_count"] = verification.new_sign_count
    _save_credentials(creds)
    logger.info("WebAuthn: authentication successful")
    return True, "ok"


def _find_and_consume_challenge(body: dict) -> bytes | None:
    """Find the pending challenge from clientDataJSON and consume it."""
    import base64
    try:
        client_data_b64 = body.get("response", {}).get("clientDataJSON", "")
        # Add padding
        padding = 4 - len(client_data_b64) % 4
        if padding != 4:
            client_data_b64 += "=" * padding
        client_data = json.loads(base64.urlsafe_b64decode(client_data_b64))
        challenge_b64 = client_data.get("challenge", "")

        # Look up and consume the stored challenge
        challenge = _pending_challenges.pop(challenge_b64, None)
        if challenge is not None:
            return challenge

        # Fallback: decode the challenge from the client data
        return base64url_to_bytes(challenge_b64)
    except Exception as e:
        logger.warning("WebAuthn: failed to extract challenge: %s", e)
        return None


def _get_expected_origins() -> list[str]:
    """Get expected origins for verification."""
    rp_id = _get_rp_id()
    origins = [f"https://{rp_id}:{config.PORT}", f"https://{rp_id}"]
    if rp_id == "localhost":
        origins.append(f"http://localhost:{config.PORT}")
    return origins
