"""Webhook endpoint logic for Antkeeper workflow triggers.

This module provides the Pydantic request/response models and handler function
for the /webhook HTTP endpoint. Incoming POST requests specify a workflow by
name and optional initial state; the workflow is executed asynchronously in the
background and the caller receives an immediate response with a unique run ID.
"""
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from pydantic import BaseModel

from antkeeper.channels.api import ApiChannel
from antkeeper.core.app import App
from antkeeper.core.runner import Runner
from antkeeper.http import run_workflow_background


class WebhookRequest(BaseModel):
    """Request model for webhook endpoint.

    Attributes:
        workflow_name: Name of the registered workflow handler to invoke.
        initial_state: Optional initial state dictionary to pass to the workflow.

    """

    workflow_name: str
    initial_state: dict[str, Any] = {}


class WebhookResponse(BaseModel):
    """Response model for webhook endpoint.

    Attributes:
        run_id: Unique identifier for the initiated workflow run.

    """

    run_id: str


async def handle_webhook(request: WebhookRequest, background_tasks: BackgroundTasks, antkeeper_app: App) -> WebhookResponse:
    """Handle incoming webhook requests to trigger Antkeeper workflows.

    Validates the workflow exists, creates a Runner with an ApiChannel, and
    schedules the workflow execution in the background. Returns immediately
    with a run ID for tracking.

    Args:
        request: Webhook request containing workflow name and initial state.
        background_tasks: FastAPI background tasks manager for async execution.
        antkeeper_app: The Antkeeper application instance with registered handlers.

    Returns:
        WebhookResponse: Object containing the unique run ID for tracking the workflow.

    Raises:
        HTTPException: 404 error if the specified workflow name is not registered.
    """
    try:
        antkeeper_app.get_handler(request.workflow_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {request.workflow_name}")

    channel = ApiChannel(request.workflow_name, request.initial_state)
    runner = Runner(antkeeper_app, channel)
    background_tasks.add_task(run_workflow_background, runner)
    return WebhookResponse(run_id=runner.id)
