import io
import sys
import time

from src.rag.utils import ProgressBar


def _last_line(buffer: io.StringIO) -> str:
    return buffer.getvalue().split("\r")[-1]


class _Tee:
    """Simple stdout/collector tee to show live output and keep assertions."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)

    def flush(self):
        for stream in self.streams:
            flush = getattr(stream, "flush", None)
            if flush:
                flush()


def test_progress_bar_updates_without_scrolling_and_finishes_with_newline():
    buf = io.StringIO()
    bar = ProgressBar(total=3, stream=buf, prefix="Test", rewrite=True)

    bar.advance()
    bar.advance()

    before_finish = buf.getvalue()
    # Should only use carriage returns while running (no new lines yet).
    assert before_finish.count("\n") == 0
    assert "(2/3)" in _last_line(buf)

    bar.finish()

    after_finish = buf.getvalue()
    assert after_finish.endswith("\n")
    assert "(3/3)" in _last_line(buf).strip()


def test_progress_bar_track_advances_iterable_and_returns_items():
    buf = io.StringIO()
    bar = ProgressBar(total=3, stream=buf, rewrite=True)

    items = list(bar.track([1, 2, 3]))

    assert items == [1, 2, 3]
    assert "(3/3)" in _last_line(buf).strip()
    assert buf.getvalue().count("\n") == 1  # newline only at completion


def test_progress_bar_clears_longer_previous_line():
    buf = io.StringIO()
    bar = ProgressBar(total=3, stream=buf, rewrite=True)

    bar.update(1, message="long-message")
    bar.update(2, message="short")

    assert "long-message" not in _last_line(buf)
    assert "(2/3)" in _last_line(buf)


def test_progress_bar_counts_zero_to_twenty():
    buf = io.StringIO()
    bar = ProgressBar(total=20, stream=buf, prefix="Count", rewrite=True)

    for i in range(0, 21):  # inclusive from 0 to 20
        bar.update(i)

    bar.finish()

    output = buf.getvalue()
    assert "(20/20)" in _last_line(buf)
    assert "100.00%" in _last_line(buf)
    assert output.count("\n") == 1  # only the final newline


def test_progress_bar_visual_demo(capsys):
    """Runs a short demo (0..20) to show the bar in terminal; use -s to view live."""
    buf = io.StringIO()
    tee = _Tee(sys.stdout, buf)

    with capsys.disabled():
        bar = ProgressBar(total=20, stream=tee, prefix="Demo", rewrite=True)

        for i in range(0, 21):
            bar.update(i, message=f"paso {i}")
            time.sleep(0.002)  # tiny delay to see motion if run with -s

        bar.finish()

    captured = buf.getvalue()
    assert "(20/20)" in captured
    assert "100.00%" in captured
