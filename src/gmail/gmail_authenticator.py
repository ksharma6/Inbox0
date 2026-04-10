import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.freebusy",
]


def auth_user(path):
    """Authenticate user's Gmail account access and saves credentials to token.json file.

    Args:
        path (string): file path to directory where user's gmail token.json file exists. If not provided,
        defaults to current working directory.

    Returns:
        creds: Authenticated token from user
    """
    creds = None
    if os.path.exists(path + "token.json"):
        creds = Credentials.from_authorized_user_file(path + "token.json", SCOPES)

    # user login flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(path + "credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        # save credentials
        with open(path + "token.json", "w") as token:
            token.write(creds.to_json())

    print("user successfully authenticated")

    return creds
