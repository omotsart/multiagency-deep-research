import os
from typing import Dict

import sendgrid
from sendgrid.helpers.mail import Email, Mail, Content, To
from agents import Agent, function_tool


# Адреса берём из окружения — хардкодить email запрещено (RULES §5).
# Если переменные не заданы, используем очевидные заглушки-плейсхолдеры.
EMAIL_FROM = os.environ.get("EMAIL_FROM", "sender@example.com")
EMAIL_TO = os.environ.get("EMAIL_TO", "recipient@example.com")


@function_tool
def send_email(subject: str, html_body: str) -> Dict[str, str]:
    """Send an email with the given subject and HTML body"""
    sg = sendgrid.SendGridAPIClient(api_key=os.environ.get("SENDGRID_API_KEY"))
    from_email = Email(EMAIL_FROM)  # verified sender, из окружения
    to_email = To(EMAIL_TO)  # recipient, из окружения
    content = Content("text/html", html_body)
    mail = Mail(from_email, to_email, subject, content).get()
    response = sg.client.mail.send.post(request_body=mail)
    print("Email response", response.status_code)
    return "success"


INSTRUCTIONS = """You are able to send a nicely formatted HTML email based on a detailed report.
You will be provided with a detailed report. You should use your tool to send one email, providing the 
report converted into clean, well presented HTML with an appropriate subject line."""

email_agent = Agent(
    name="Email agent",
    instructions=INSTRUCTIONS,
    tools=[send_email],
    model="gpt-4o-mini",
)
