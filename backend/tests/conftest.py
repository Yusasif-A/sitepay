import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MONGO_URI"] = "mongomock://"
os.environ["PAYPAL_CLIENT_ID"] = ""
os.environ["PAYPAL_CLIENT_SECRET"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["WHATSAPP_TOKEN"] = ""
os.environ["WHATSAPP_APP_SECRET"] = ""
os.environ["DOTENV_SKIP"] = "1"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    import db
    import paypal
    db.reset_for_tests()
    paypal.set_client(None)
    os.environ.pop("PAYPAL_MODE", None)
    yield
    db.reset_for_tests()
