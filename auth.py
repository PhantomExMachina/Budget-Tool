import os
from functools import lru_cache

try:
    import firebase_admin
    from firebase_admin import auth, credentials
except Exception:  # pragma: no cover - optional dependency
    firebase_admin = None
    auth = None
    credentials = None


@lru_cache(maxsize=1)
def init_firebase():
    if firebase_admin is None:
        raise RuntimeError("firebase_admin not installed")
    cred_path = os.environ.get("FIREBASE_CREDENTIALS")
    if not cred_path:
        raise RuntimeError("FIREBASE_CREDENTIALS not set")
    try:
        firebase_admin.get_app()
    except ValueError:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)


def verify_id_token(id_token: str) -> dict:
    init_firebase()
    return auth.verify_id_token(id_token)
