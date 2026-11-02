"""Keep the developer's real .env out of the test run.

app.config.settings loads .env at import time; tests that assert on
defaults must see a clean environment, not whatever is configured on
this machine.
"""

import os

os.environ["JARVIS_SKIP_DOTENV"] = "1"
