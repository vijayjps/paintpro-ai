import logging
from crew import run_crew
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Painting Lead Generation Agent")

    # Run the crew
    result = run_crew()

    # Extract the email draft from result
    # Assuming the last task output is the email
    email_draft = result  # Need to parse properly, but for now

    print("Email Draft:")
    print(email_draft)

    # Human approval
    approval = input("Approve sending this email? (yes/no): ").strip().lower()
    if approval == "yes":
        # Send email via Brevo
        send_email(email_draft)
        logger.info("Email sent successfully")
    else:
        logger.info("Email not sent - human declined")

def send_email(draft):
    # Implement Brevo sending
    # Use requests to post to Brevo API
    import requests
    api_key = os.getenv("BREVO_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    from_name = os.getenv("FROM_NAME")

    # Parse draft to get subject, body, etc.
    # For now, placeholder
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    data = {
        "sender": {"name": from_name, "email": from_email},
        "to": [{"email": "recipient@example.com"}],  # Need to get from draft
        "subject": "Subject",
        "htmlContent": "<p>Body</p>"
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        print("Email sent")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    main()