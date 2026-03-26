"""Tests for middleware pipeline and extraction middleware.

Covers build_pipeline(), extraction middleware factory, and edge cases.
"""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from antkeeper.core.domain import StreamEvent
from antkeeper.handlers.claude_code.factories import (
    build_pipeline,
    _extraction_middleware,
)


class TestBuildPipeline:
    """Tests for build_pipeline()."""

    def test_no_middlewares_identity(self):
        """No middlewares — identity pass-through."""
        events = [StreamEvent(type="progress", content="a")]
        result = list(build_pipeline(iter(events), []))
        assert len(result) == 1
        assert result[0].content == "a"

    def test_single_middleware_transforms(self):
        """Single middleware transforms the stream."""
        def upper_mw(stream: Iterator[StreamEvent]) -> Iterator[StreamEvent]:
            for e in stream:
                yield StreamEvent(type=e.type, content=e.content.upper())

        events = [StreamEvent(type="progress", content="hello")]
        result = list(build_pipeline(iter(events), [upper_mw]))
        assert result[0].content == "HELLO"

    def test_sequential_order(self):
        """Middlewares applied left-to-right."""
        def append_a(stream: Iterator[StreamEvent]) -> Iterator[StreamEvent]:
            for e in stream:
                yield StreamEvent(type=e.type, content=e.content + "A")

        def append_b(stream: Iterator[StreamEvent]) -> Iterator[StreamEvent]:
            for e in stream:
                yield StreamEvent(type=e.type, content=e.content + "B")

        events = [StreamEvent(type="progress", content="x")]
        result = list(build_pipeline(iter(events), [append_a, append_b]))
        assert result[0].content == "xAB"


class TestExtractionMiddleware:
    """Tests for the extraction middleware factory."""

    @patch("antkeeper.handlers.claude_code.factories.run_prompt")
    def test_intercepts_result(self, mock_rp):
        """Triggers extraction on result event."""
        mock_rp.return_value = iter([
            StreamEvent(type="result", content='{"field": "value"}'),
        ])

        mw = _extraction_middleware(["field"], __import__("logging").getLogger("test"), ("haiku", ["--max-turns", "1"]))
        events = [
            StreamEvent(type="result", content="raw response"),
        ]
        result = list(mw(iter(events)))
        assert mock_rp.called
        # Original result + extraction result
        assert len(result) == 2

    @patch("antkeeper.handlers.claude_code.factories.run_prompt")
    def test_splices_internal_events(self, mock_rp):
        """Extraction events have internal=True."""
        mock_rp.return_value = iter([
            StreamEvent(type="result", content='{"x": 1}'),
        ])

        mw = _extraction_middleware(["x"], __import__("logging").getLogger("test"), ("haiku", None))
        events = [StreamEvent(type="result", content="raw")]
        result = list(mw(iter(events)))
        # First event is original (not internal), second is extraction (internal)
        assert result[0].internal is False
        assert result[1].internal is True

    @patch("antkeeper.handlers.claude_code.factories.run_prompt")
    def test_passes_non_result_events(self, mock_rp):
        """Progress events pass through unchanged."""
        mw = _extraction_middleware(["x"], __import__("logging").getLogger("test"), ("haiku", None))
        events = [StreamEvent(type="progress", content="hello")]
        result = list(mw(iter(events)))
        assert len(result) == 1
        assert result[0].type == "progress"
        mock_rp.assert_not_called()

    @patch("antkeeper.handlers.claude_code.factories.run_prompt")
    def test_extraction_error_propagates(self, mock_rp):
        """Extraction failure propagates as exception."""
        mock_rp.side_effect = ValueError("bad extraction")

        mw = _extraction_middleware(["x"], __import__("logging").getLogger("test"), ("haiku", None))
        events = [StreamEvent(type="result", content="raw")]
        with pytest.raises(ValueError, match="bad extraction"):
            list(mw(iter(events)))
