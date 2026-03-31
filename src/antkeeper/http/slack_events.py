"""Slack event handling: event routing, pending message store, debounce timers.

Receives Slack Events API payloads, accumulates edits and thread replies
with a debounce timer, then dispatches to workflow handlers.
"""
import asyncio
import logging
import os
import re
from dataclasses import dataclass, field

import httpx

from antkeeper.channels.slack import SlackChannel
from antkeeper.core.app import App
from antkeeper.core.runner import Runner
from antkeeper.http import run_workflow_background

logger = logging.getLogger("antkeeper.http.slack_events")


def is_bot_message(event: dict) -> bool:
    """Check if a Slack event is from a bot.

    Used to filter out bot messages and prevent infinite loops where the
    bot responds to its own messages.

    Args:
        event: Slack event dictionary from the Events API.

    Returns:
        bool: True if the event contains a bot_id field, False otherwise.
    """
    return bool(event.get("bot_id"))


def is_bot_mention(text: str, bot_user_id: str) -> bool:
    """Check if text contains a mention of the bot user.

    Searches for Slack's mention format: <@USER_ID> in the message text.

    Args:
        text: Message text to check for mentions.
        bot_user_id: Slack user ID of the bot (e.g., "U12345678").

    Returns:
        bool: True if the text contains a mention of the bot user ID, False otherwise.
    """
    return f"<@{bot_user_id}>" in text


def strip_mention(text: str) -> str:
    """Remove bot mention from the beginning of text.

    Uses regex to strip Slack mention format (<@U...>) and surrounding whitespace
    from the start of the message.

    Args:
        text: Message text potentially containing a bot mention.

    Returns:
        str: Text with leading bot mention and surrounding whitespace removed.
    """
    return re.sub(r"^\s*<@U[A-Z0-9]+>\s*", "", text)


@dataclass
class PendingMessage:
    """Represents a Slack message waiting for debounce timer.

    Accumulates edits and thread replies while a cooldown timer is active.
    Once the timer fires, dispatches the accumulated message to a workflow.

    Attributes:
        channel_id: Slack channel ID where the message was posted.
        ts: Slack timestamp identifier for the message.
        user: Slack user ID who sent the message.
        text: Accumulated message text (updated on edits and thread replies).
        files: List of file attachments from the message and thread replies.
        workflow_name: Name of the workflow handler to dispatch to.
        timer_task: Active asyncio timer task, or None if not running.

    """

    channel_id: str
    ts: str
    user: str
    text: str
    files: list[dict]
    workflow_name: str
    timer_task: asyncio.Task | None = field(default=None, repr=False)


async def slack_api(token: str, method: str, payload: dict) -> dict:
    """Call a Slack API method with the given payload.

    Makes an asynchronous HTTP POST request to the specified Slack Web API method
    with bearer token authentication.

    Args:
        token: Slack bot token for authorization (xoxb-...).
        method: Slack API method name (e.g., "chat.postMessage", "reactions.add").
        payload: JSON payload to send in the request body.

    Returns:
        dict: JSON response from the Slack API as a dictionary.

    Raises:
        httpx.HTTPError: If the HTTP request fails.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://slack.com/api/{method}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        return resp.json()


class SlackEventProcessor:
    """Process Slack Events API payloads with debounce and workflow dispatch.

    This processor receives Slack events, accumulates message edits and thread
    replies within a cooldown period, then dispatches the final accumulated
    message to the appropriate workflow handler.

    Attributes:
        _app: Antkeeper App instance containing registered workflow handlers.
        _pending: Dictionary mapping (channel_id, ts) tuples to pending messages
            awaiting debounce timer expiration.

    """

    def __init__(self, antkeeper_app: App) -> None:
        """Initialize the Slack event processor.

        Args:
            antkeeper_app: Antkeeper App instance with registered workflow handlers.
        """
        self._app = antkeeper_app
        self._pending: dict[tuple[str, str], PendingMessage] = {}

    async def handle_event(self, body: dict) -> dict:
        """Route Slack event to appropriate handler based on event type.

        Handles URL verification, bot message filtering, and dispatches to
        specialized handlers for thread replies, edits, deletes, and mentions.

        Args:
            body: Slack Events API request body containing the event payload.

        Returns:
            dict: Response dictionary for Slack API. Contains {"ok": True} for success,
                or {"challenge": "..."} for URL verification.
        """
        if body.get("type") == "url_verification":
            return {"challenge": body["challenge"]}

        event = body.get("event", {})
        if not event:
            return {"ok": True}

        if is_bot_message(event):
            return {"ok": True}

        token = os.environ.get("SLACK_BOT_TOKEN", "")
        bot_user_id = os.environ.get("SLACK_BOT_USER_ID", "")
        cooldown = float(os.environ.get("SLACK_COOLDOWN_SECONDS", "30"))

        channel_id = event.get("channel", "")
        event_ts = event.get("ts", "")

        if event.get("thread_ts") and event["ts"] != event["thread_ts"]:
            return await self._handle_thread_reply(event, channel_id, event_ts, token, cooldown)

        if event.get("subtype") == "message_changed":
            return await self._handle_edit(event, channel_id, token, cooldown)

        if event.get("subtype") == "message_deleted":
            return self._handle_delete(event, channel_id)

        event_type = event.get("type", "")
        subtype = event.get("subtype")
        if event_type in ("app_mention", "message") and subtype in (None, "file_share"):
            return await self._handle_mention(event, channel_id, event_ts, bot_user_id, token, cooldown)

        return {"ok": True}

    async def _handle_thread_reply(self, event: dict, channel_id: str, event_ts: str, token: str, cooldown: float) -> dict:
        """Handle a reply posted to an existing thread.

        If a pending message exists for the parent thread, accumulates the
        reply text and files, cancels the existing timer, and starts a new
        debounce timer.

        Args:
            event: Slack event dictionary containing the thread reply.
            channel_id: Slack channel ID where the reply was posted.
            event_ts: Slack timestamp of the reply message.
            token: Slack bot token for API calls.
            cooldown: Debounce cooldown period in seconds.

        Returns:
            dict: Response dictionary {"ok": True}.
        """
        key = (channel_id, event["thread_ts"])
        if key in self._pending:
            entry = self._pending[key]
            if entry.timer_task:
                entry.timer_task.cancel()
            entry.text += "\n" + event.get("text", "")
            entry.files.extend(event.get("files", []))
            entry.timer_task = asyncio.create_task(
                self._on_timer_fire(key, token, cooldown)
            )
            await slack_api(token, "reactions.add", {
                "channel": channel_id,
                "timestamp": event_ts,
                "name": "thumbsup",
            })
        return {"ok": True}

    async def _handle_edit(self, event: dict, channel_id: str, token: str, cooldown: float) -> dict:
        """Handle an edit to an existing message.

        If a pending message exists for the edited message, updates the
        accumulated text, cancels the existing timer, and starts a new
        debounce timer.

        Args:
            event: Slack event dictionary containing the edit event.
            channel_id: Slack channel ID where the message was edited.
            token: Slack bot token for API calls.
            cooldown: Debounce cooldown period in seconds.

        Returns:
            dict: Response dictionary {"ok": True}.
        """
        nested = event.get("message", {})
        key = (channel_id, nested.get("ts", ""))
        if key in self._pending:
            entry = self._pending[key]
            if entry.timer_task:
                entry.timer_task.cancel()
            entry.text = strip_mention(nested.get("text", ""))
            entry.timer_task = asyncio.create_task(
                self._on_timer_fire(key, token, cooldown)
            )
        return {"ok": True}

    def _handle_delete(self, event: dict, channel_id: str) -> dict:
        """Handle a message deletion event.

        If a pending message exists for the deleted message, cancels the
        timer and removes the entry from the pending messages dictionary.

        Args:
            event: Slack event dictionary containing the deletion event.
            channel_id: Slack channel ID where the message was deleted.

        Returns:
            dict: Response dictionary {"ok": True}.
        """
        key = (channel_id, event.get("deleted_ts", ""))
        if key in self._pending:
            entry = self._pending[key]
            if entry.timer_task:
                entry.timer_task.cancel()
            del self._pending[key]
        return {"ok": True}

    async def _handle_mention(self, event: dict, channel_id: str, event_ts: str, bot_user_id: str, token: str, cooldown: float) -> dict:
        """Handle a bot mention or message in the channel.

        When the bot is mentioned, extracts the workflow name from the first
        word after the mention, creates a pending message entry, adds a
        reaction, and starts the debounce timer.

        Args:
            event: Slack event dictionary containing the mention or message.
            channel_id: Slack channel ID where the mention occurred.
            event_ts: Slack timestamp of the mention message.
            bot_user_id: Slack user ID of the bot.
            token: Slack bot token for API calls.
            cooldown: Debounce cooldown period in seconds.

        Returns:
            dict: Response dictionary {"ok": True}.
        """
        text = event.get("text", "")
        if is_bot_mention(text, bot_user_id):
            clean_text = strip_mention(text)
            parts = clean_text.split()
            workflow_name = parts[0] if parts else ""

            key = (channel_id, event_ts)
            if key in self._pending:
                return {"ok": True}

            entry = PendingMessage(
                channel_id=channel_id,
                ts=event_ts,
                user=event.get("user", ""),
                text=clean_text,
                files=event.get("files", []),
                workflow_name=workflow_name,
            )
            self._pending[key] = entry

            await slack_api(token, "reactions.add", {
                "channel": channel_id,
                "timestamp": event_ts,
                "name": "thumbsup",
            })

            entry.timer_task = asyncio.create_task(
                self._on_timer_fire(key, token, cooldown)
            )

            return {"ok": True}

        return {"ok": True}

    async def _on_timer_fire(self, key: tuple[str, str], token: str, cooldown: float) -> None:
        """Execute after debounce cooldown period expires.

        Waits for the cooldown period, retrieves the accumulated pending
        message, validates the workflow exists, then dispatches to the
        workflow handler via a background thread. Posts status messages
        to Slack to inform the user of processing state.

        Args:
            key: Tuple of (channel_id, ts) identifying the pending message.
            token: Slack bot token for API calls.
            cooldown: Cooldown period in seconds to wait before processing.

        """
        await asyncio.sleep(cooldown)
        entry = self._pending.pop(key, None)
        if entry is None:
            return

        await slack_api(token, "chat.postMessage", {
            "channel": entry.channel_id,
            "thread_ts": entry.ts,
            "text": "Processing your request...",
        })

        try:
            self._app.get_handler(entry.workflow_name)
        except ValueError:
            await slack_api(token, "chat.postMessage", {
                "channel": entry.channel_id,
                "thread_ts": entry.ts,
                "text": f"Unknown workflow: {entry.workflow_name}",
            })
            return

        initial_state: dict = {"prompt": entry.text, "slack_user": entry.user}
        if entry.files:
            initial_state["files"] = entry.files

        channel = SlackChannel(
            workflow_name=entry.workflow_name,
            initial_state=initial_state,
            slack_token=token,
            channel_id=entry.channel_id,
            thread_ts=entry.ts,
            verbose=os.environ.get("ANTKEEPER_SLACK_VERBOSE", "").lower() in ("1", "true"),
        )
        runner = Runner(self._app, channel)
        await asyncio.to_thread(run_workflow_background, runner)
