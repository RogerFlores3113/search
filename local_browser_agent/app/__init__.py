"""local-browser-agent web app (`local_browser_agent.app`).

browser-use sends anonymized telemetry (and, by default, cloud sync follows it)
unless told otherwise. This app promises that nothing leaves the machine except
LLM API calls, so both are switched off here, before browser_use is imported
anywhere in the app. An inherited ANONYMIZED_TELEMETRY=true is overridden; opt in
explicitly with LBA_ALLOW_TELEMETRY=1 (the same rule as the library package).
"""
import os

if os.environ.get("LBA_ALLOW_TELEMETRY") != "1":
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
