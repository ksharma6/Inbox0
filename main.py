import atexit
import logging
import os
from logging.handlers import TimedRotatingFileHandler

from flask import Flask
from slack_bolt import App as SlackApp
from src.routes.integrations_slack.slack_routes import register_slack_routes
from src.routes.web.flask_routes import register_flask_routes
from src.utils.json_formatter import JsonFormatter
from src.utils.load_env import load_dotenv_helper
from src.workflows.factory import get_workflow

app = Flask(__name__)

load_dotenv_helper()

handler = TimedRotatingFileHandler(
    filename=os.getenv("LOG_FILE"),
    when="midnight",
    interval=1,
    backupCount=30,
)
handler.setFormatter(JsonFormatter())

root = logging.getLogger()
root.setLevel(logging.INFO)
root.addHandler(handler)
root.info("Starting the application")

slack_app = SlackApp(
    token=os.getenv("SLACK_BOT_TOKEN"),
    signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
)
# initialize workflow, register flask and slack routes
workflow = get_workflow(slack_app)
register_flask_routes(app, workflow)
register_slack_routes(app, slack_app, workflow)

if __name__ == "__main__":
    app.run(port=5002, debug=False)
    atexit.register(lambda: root.info("Application shutdown completed"))
