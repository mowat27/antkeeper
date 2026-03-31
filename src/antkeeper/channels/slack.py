"""Slack channel implementation for Antkeeper workflows.

Posts handler progress and error messages to the originating Slack thread
via synchronous httpx.Client calls.
"""
import logging

import httpx

from antkeeper.core.domain import State, StreamEvent

logger = logging.getLogger("antkeeper.channels.slack")


class SlackChannel:
    """Channel implementation for Slack thread-based workflow execution.

    Posts progress and error messages to a specific Slack thread using
    the Slack Web API. Uses synchronous httpx because handler code runs
    in a threadpool via asyncio.to_thread.

    Attributes:
        type: Channel type identifier ("slack").
        workflow_name: Name of the workflow to execute.
        initial_state: Initial state dictionary for the workflow.
    """

    def __init__(
        self,
        workflow_name: str,
        initial_state: State | None = None,
        *,
        slack_token: str,
        channel_id: str,
        thread_ts: str,
    ) -> None:
        """Initialize a SlackChannel instance.

        Args:
            workflow_name: Name of the workflow to execute.
            initial_state: Optional initial state dictionary. Defaults to empty dict.
            slack_token: Slack bot token for API authentication.
            channel_id: Slack channel ID where the workflow was triggered.
            thread_ts: Timestamp of the thread to post messages to.
        """
        self.type = "slack"
        self.workflow_name = workflow_name
        self.initial_state: State = {**(initial_state or {})}
        self._slack_token = slack_token
        self._channel_id = channel_id
        self._thread_ts = thread_ts
        logger.debug(f"SlackChannel initialized: channel={channel_id}, thread_ts={thread_ts}")

    def _post_to_thread(self, text: str) -> None:
        """Post a message to the Slack thread.

        Uses synchronous httpx.Client to post messages to Slack via the
        chat.postMessage API endpoint. This is synchronous because handler
        code runs in a threadpool via asyncio.to_thread. Logs errors but
        does not raise exceptions.

        Args:
            text: Message text to post to the thread.
        """
        try:
            with httpx.Client() as client:
                client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {self._slack_token}"},
                    json={
                        "channel": self._channel_id,
                        "thread_ts": self._thread_ts,
                        "text": text,
                    },
                )
        except httpx.HTTPError as exc:
            logger.error(f"Failed to post to Slack thread: {exc}")

    def report(self, run_id: str, event: StreamEvent) -> None:
        """Report a workflow event to the Slack thread.

        Args:
            run_id: Unique identifier for the workflow run.
            event: The stream event to report.
        """
        if event.internal:
            return
        if event.type == "error":
            self._post_to_thread(f"[{self.workflow_name}, {run_id}] [ERROR] {event.content}")
        else:
            self._post_to_thread(f"[{self.workflow_name}, {run_id}] {event.content}")
