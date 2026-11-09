"""local-browser-agent web app (`local_browser_agent.app`).

browser-use sends anonymized telemetry (and, by default, cloud sync follows it)
unless told otherwise. This app promises that nothing leaves the machine except
LLM API calls, so both are switched off here, before browser_use is imported
anywhere in the app. `setdefault` keeps an explicit user opt-in working.
"""
import os

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")
