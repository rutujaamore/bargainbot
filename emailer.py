"""
Sends the "price dropped" email for a triggered alert.

Design rule, same spirit as llm_explainer.py
----------------------------------------------
This function is only ever given numbers that were already calculated
by real code (the scraped price, the target price, the product name).
It never invents anything - it just formats an email.

If email isn't configured, or Gmail rejects the login, or the network
is down - this fails quietly and returns False. A broken email should
never crash the scheduler or the price search.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from email_config import (
    SENDER_EMAIL,
    SENDER_APP_PASSWORD,
    SMTP_HOST,
    SMTP_PORT,
)


def is_email_configured():
    """True only once the placeholder values in email_config.py have
    actually been replaced with real credentials."""
    return (
        SENDER_EMAIL
        and SENDER_APP_PASSWORD
        and "your_email" not in SENDER_EMAIL
        and "your_16_char" not in SENDER_APP_PASSWORD
    )


def send_price_alert_email(to_email, product_name, current_price, target_price, platform=None, link=None):
    """
    Sends one plain-text/HTML price-drop email.

    Returns True if the email was sent, False otherwise (including
    "email not configured" - that's not an error, just a no-op).
    """

    if not is_email_configured():
        print("[Emailer] Skipped - email_config.py still has placeholder credentials.")
        return False

    if not to_email or current_price is None or target_price is None:
        return False

    subject = f"BargainBot Alert: {product_name} dropped to your target price!"

    savings = max(0, target_price - current_price)

    body_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #14182b;">
        <h2>Good news - your price target was hit! 🎉</h2>
        <p><b>Product:</b> {product_name}</p>
        <p><b>Current price:</b> ₹{current_price:,}</p>
        <p><b>Your target price:</b> ₹{target_price:,}</p>
        {f'<p><b>Platform:</b> {platform}</p>' if platform else ''}
        {f'<p><a href="{link}">View listing &rarr;</a></p>' if link else ''}
        <hr>
        <p style="font-size: 12px; color: #565b78;">
          You're receiving this because you set a BargainBot price alert
          for this product. This is a one-time notification for this
          target - set a new alert if you'd like to keep tracking it.
        </p>
      </body>
    </html>
    """

    body_text = (
        f"Your BargainBot price alert was triggered!\n\n"
        f"Product: {product_name}\n"
        f"Current price: Rs.{current_price:,}\n"
        f"Your target price: Rs.{target_price:,}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())

        print(f"[Emailer] Alert email sent to {to_email} for '{product_name}'.")
        return True

    except Exception as e:
        print(f"[Emailer] Failed to send email: {e}")
        return False
