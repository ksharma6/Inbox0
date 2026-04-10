from slack_sdk import WebClient


def authenticate_slack(token):
    try:
        client = WebClient(token=token)
    except Exception as e:
        print(f"Error: Could not initialize Slack client. Please check your token. Details: {e}")
        exit()
    return client
