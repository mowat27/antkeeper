# Slack Integration

Antkeeper integrates with Slack via the Events API. When a user @mentions the bot in a channel, Antkeeper collects the message (and any follow-up edits or thread replies within a cooldown window), then dispatches a workflow and posts results back to the originating thread.

## Slack App Configuration

### Required Bot Token Scopes

| Scope | Purpose |
|---|---|
| `app_mentions:read` | Receive events when the bot is @mentioned. |
| `channels:history` | Read messages in public channels the bot is in. |
| `chat:write` | Post messages and replies to channels. |
| `reactions:write` | Add thumbsup reaction to acknowledge received messages. |

### Event Subscriptions

Enable **Event Subscriptions** in the Slack app settings. Set the Request URL to:

```
https://<your-host>/slack_event
```

Subscribe to the following bot events:

- `app_mention` -- triggered when a user @mentions the bot.
- `message.channels` -- triggered on messages in public channels the bot is in (needed for edits, deletes, and thread replies).

### URL Verification

Slack sends a `url_verification` challenge when you first set the Request URL. The `/slack_event` endpoint handles this automatically by returning `{"challenge": "<value>"}`.

## Environment Variables

| Variable | Default | Description | Required |
|---|---|---|---|
| `SLACK_BOT_TOKEN` | (empty string) | Bot User OAuth Token from Slack app settings (starts with `xoxb-`). Used for all Slack API calls. | Yes |
| `SLACK_BOT_USER_ID` | (empty string) | The Slack user ID of the bot (e.g. `U07ABC123`). Used to detect @mentions in message text. Find this under the bot's profile in Slack. | Yes |
| `SLACK_COOLDOWN_SECONDS` | `30` | Number of seconds to wait after the last interaction before dispatching the workflow. Resets on edits and thread replies. | No |

### .env File Support

The server calls `dotenv.load_dotenv()` at startup (in `create_app()`), so all three variables can be placed in a `.env` file in the working directory:

```
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_BOT_USER_ID=U07ABC123
SLACK_COOLDOWN_SECONDS=30
```

### Environment Variable Validation

The `/slack_event` endpoint validates that `SLACK_BOT_TOKEN` and `SLACK_BOT_USER_ID` are present and non-empty before processing events. If either variable is missing, the endpoint returns HTTP 422 with a diagnostic message:

```json
{
    "detail": "Missing required environment variables: SLACK_BOT_TOKEN, SLACK_BOT_USER_ID"
}
```

The error message lists only the variables that are actually missing (e.g., if only `SLACK_BOT_TOKEN` is missing, the message will say `"Missing required environment variables: SLACK_BOT_TOKEN"`).

**Exception:** `url_verification` events bypass validation. This allows Slack to complete the initial app setup handshake before environment variables are configured. During URL verification, Slack sends a challenge payload that the endpoint must echo back, and this flow works regardless of env var state.

## Runtime Behaviour Flow

1. **User @mentions the bot** in a channel message, e.g. `@AntBot review fix the login bug`.
2. The `/slack_event` endpoint receives the event from Slack and delegates to `SlackEventProcessor.handle_event()`.
3. **Bot self-filter**: if the event has a `bot_id` field, it is ignored (prevents the bot from responding to its own messages).
4. **Thumbsup reaction**: the bot adds a thumbsup reaction to the message to acknowledge receipt.
5. **Cooldown timer starts**: a debounce timer of `SLACK_COOLDOWN_SECONDS` begins.
6. **Edits and thread replies accumulate**: if the user edits the original message or posts thread replies before the timer fires, the timer resets and the new content is folded into the pending message.
7. **Timer fires**: once the cooldown elapses with no further interaction:
   - The bot posts "Processing your request..." in the thread.
   - The workflow name is looked up in the App's handler registry.
   - A `SlackChannel` and `Runner` are created.
   - The workflow executes via `asyncio.to_thread(run_workflow_background, runner)`.
8. **Workflow results** are posted back to the same thread via the `SlackChannel`.

## Workflow Name Extraction

The workflow name is the first word of the message text after stripping the @mention:

```
@AntBot review fix the login bug
        ^^^^^^
        workflow_name = "review"
```

The @mention prefix (e.g. `<@U07ABC123>`) is stripped using a regex. The remaining text is split on whitespace and the first token becomes the workflow name. The full stripped text (including the workflow name) is passed as the `prompt` field in the initial state.

## Event Routing

The `/slack_event` endpoint processes events in the following order:

| Step | Condition | Action |
|---|---|---|
| 1. URL verification | `body.type == "url_verification"` | Return `{"challenge": body.challenge}`. |
| 2. Empty event | No `event` field in body | Return `{"ok": true}`. |
| 3. Bot self-filter | `event.bot_id` is present | Return `{"ok": true}`. |
| 4. Thread reply | `event.thread_ts` exists and differs from `event.ts` | If the parent message is pending: cancel timer, append reply text and files, restart timer, add thumbsup. |
| 5. Message edit | `event.subtype == "message_changed"` | If the original message is pending: cancel timer, replace text with edited content, restart timer. |
| 6. Message delete | `event.subtype == "message_deleted"` | If the deleted message is pending: cancel timer, remove from pending store. |
| 7. Bot mention | Event type is `app_mention` or `message`, subtype is `None` or `file_share`, and text contains `<@BOT_USER_ID>` | Create `PendingMessage`, add thumbsup, start cooldown timer. |
| 8. All other events | Anything else | Return `{"ok": true}`. |

Thread replies and message edits are checked before bot mentions. This ensures that follow-up interactions on an already-pending message reset the timer rather than creating a duplicate entry.

## Debounce Mechanism

The debounce system prevents premature dispatch when users are still composing their request across multiple messages or edits.

### SlackEventProcessor

The `SlackEventProcessor` class (in `slack_events.py`) encapsulates all Slack event handling logic and manages the pending message store as explicit instance state (`self._pending`). This replaced the previous closure-based design where the pending dict was hidden inside `setup_slack_routes()`.

Benefits:
- **Testable state**: `_pending` is accessible for inspection in tests
- **Clear ownership**: State belongs to the processor instance, not a closure
- **Focused methods**: Event handling split into `_handle_mention()`, `_handle_edit()`, `_handle_thread_reply()`, `_handle_delete()`, and `_on_timer_fire()`

### PendingMessage

Each tracked message is stored as a `PendingMessage` dataclass:

| Field | Type | Description |
|---|---|---|
| `channel_id` | `str` | Slack channel where the message was posted. |
| `ts` | `str` | Slack message timestamp (used as unique identifier). |
| `user` | `str` | Slack user ID of the message author. |
| `text` | `str` | Accumulated message text. Updated on edits; appended on thread replies. |
| `files` | `list[dict]` | File attachments from the original message and thread replies. |
| `workflow_name` | `str` | Extracted workflow name (first word after stripping @mention). |
| `timer_task` | `asyncio.Task or None` | The active cooldown timer task. |

Pending messages are keyed by `(channel_id, ts)` in the `SlackEventProcessor._pending` dictionary.

### Timer Reset Behaviour

- **On new @mention**: a new `PendingMessage` is created and a timer task is started.
- **On thread reply** to a pending message: the existing timer is cancelled, reply text is appended (`\n` separator), files are extended, and a new timer is started.
- **On message edit** of a pending message: the existing timer is cancelled, text is replaced with the edited content (re-stripped of @mention), and a new timer is started.
- **On message delete** of a pending message: the timer is cancelled and the entry is removed. No workflow is dispatched.

The default cooldown is 30 seconds, configurable via `SLACK_COOLDOWN_SECONDS`.

## SlackChannel

`SlackChannel` (in `src/antkeeper/channels/slack.py`) is the I/O boundary that posts workflow output back to the originating Slack thread.

### Construction

When the debounce timer fires, a `SlackChannel` is created with:

```python
SlackChannel(
    workflow_name=entry.workflow_name,
    initial_state={"prompt": entry.text, "slack_user": entry.user},
    slack_token=token,
    channel_id=entry.channel_id,
    thread_ts=entry.ts,
)
```

If the message included file attachments, `initial_state["files"]` is also set.

### How It Posts to Slack

`SlackChannel` uses **synchronous** `httpx.Client` to call the Slack `chat.postMessage` API. This is intentional: handler code runs in a background thread (via `asyncio.to_thread`), so synchronous HTTP is appropriate and avoids mixing sync/async concerns.

`SlackChannel.report(run_id, event)` implements the `Channel` protocol. It suppresses events with `event.internal=True` (housekeeping calls such as the extraction step). For visible events, it delegates to `_post_to_thread()`, formatting messages with the workflow name and run ID:

- Non-error events: `[workflow_name, run_id] message`
- Error events: `[workflow_name, run_id] [ERROR] message`

### Error Handling

HTTP failures in `_post_to_thread()` are caught (`httpx.HTTPError`) and logged but not propagated. This prevents a transient Slack API failure from crashing the running workflow.

## Error Handling

| Scenario | Behaviour |
|---|---|
| Unknown workflow name | After the timer fires, the bot posts `"Unknown workflow: <name>"` to the thread. No Runner is created. |
| HTTP failure posting to Slack (in SlackChannel) | Caught as `httpx.HTTPError`, logged via `logger.error()`, not propagated to the workflow. |
| `WorkflowFailedError` during execution | Caught silently by `_run_workflow()`. This is the standard signal for a workflow step failure. |
| Unexpected exception during execution | Printed to stderr by `_run_workflow()`. Does not crash the server. |
