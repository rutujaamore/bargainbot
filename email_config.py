# Gmail SMTP credentials for BargainBot's price-alert emails.
#
# Keep this file OUT of anything you share publicly (GitHub, WhatsApp,
# submitted zip files, etc.) for the same reason as llm_config.py - if
# you accidentally expose it, revoke and regenerate immediately.
#
# HOW TO GET AN APP PASSWORD (Gmail does NOT accept your normal login
# password for SMTP anymore):
#   1. Go to https://myaccount.google.com/security
#   2. Turn on 2-Step Verification if it isn't already on.
#   3. Search "App Passwords" in the account settings search bar.
#   4. Create one for "Mail" / "Other (BargainBot)".
#   5. Paste the 16-character password below (spaces don't matter).
#
# If you leave these as the placeholder values, emailer.py will detect
# that alerts aren't configured and skip sending - it will NOT crash
# the app. Alerts still get saved to the database either way.

SENDER_EMAIL = "rutujamore586@gmail.com"
SENDER_APP_PASSWORD = "ppzl tmzg kasx aljs"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
