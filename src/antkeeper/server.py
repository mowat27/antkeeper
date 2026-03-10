"""FastAPI server for Antkeeper workflows.

This module defines the FastAPI application and HTTP endpoints for executing
Antkeeper workflows via webhooks and processing Slack events. Routes are
defined here and delegate to library modules for implementation.

The module-level ``app`` object is the ASGI application instance passed to
uvicorn or any other ASGI server. It is created by calling ``create_app()``
with defaults drawn from the ``ANTKEEPER_HANDLERS_FILE`` environment variable
(falling back to ``"handlers.py"``).

Example:
    Start the server with uvicorn::

        uvicorn antkeeper.server:app --reload
"""
import os

import dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from antkeeper.cli import load_app
from antkeeper.http.webhook import WebhookRequest, WebhookResponse, handle_webhook
from antkeeper.http.slack_events import SlackEventProcessor


def create_app(agents_file: str = os.environ.get("ANTKEEPER_HANDLERS_FILE", "handlers.py")) -> FastAPI:
    """Create and configure a FastAPI application for Antkeeper workflows.

    Loads an Antkeeper app from the specified Python file and creates a FastAPI
    server with /webhook and /slack_event endpoints. Environment variables are
    loaded from .env file if present.

    Args:
        agents_file: Path to Python file containing the Antkeeper app.
            Defaults to ANTKEEPER_HANDLERS_FILE env var or "handlers.py".

    Returns:
        FastAPI: Configured FastAPI application instance with workflow routes.
    """
    dotenv.load_dotenv()
    antkeeper_app = load_app(agents_file)
    api = FastAPI()
    slack = SlackEventProcessor(antkeeper_app)

    @api.post("/webhook", response_model=WebhookResponse)
    async def webhook(request: WebhookRequest, background_tasks: BackgroundTasks):
        """Webhook endpoint for triggering Antkeeper workflows via HTTP POST.

        Args:
            request: Webhook request with workflow name and initial state.
            background_tasks: FastAPI background tasks for async execution.

        Returns:
            WebhookResponse: Response with unique run ID for the triggered workflow.
        """
        return await handle_webhook(request, background_tasks, antkeeper_app)

    @api.post("/slack_event")
    async def slack_event(request: Request):
        """Slack event endpoint for receiving and processing Slack events.

        Receives Slack event payloads, handles URL verification challenges,
        and dispatches message events to appropriate workflow handlers.

        Args:
            request: FastAPI Request object containing Slack event JSON payload.

        Returns:
            dict: JSON response for Slack event processing (challenge response or acknowledgment).
        """
        body = await request.json()
        if body.get("type") != "url_verification":
            missing = [
                var for var in ("SLACK_BOT_TOKEN", "SLACK_BOT_USER_ID")
                if not os.environ.get(var, "")
            ]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"Missing required environment variables: {', '.join(missing)}",
                )
        return await slack.handle_event(body)

    return api


app = create_app()

