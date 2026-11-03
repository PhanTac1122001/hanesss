import pytest

from harness import cli, eval as eval_mod


class FakeConsole:
    def __init__(self, answer):
        self.answer = answer
        self.printed = []

    def print(self, *args, **kwargs):
        self.printed.append(args)

    def input(self, prompt=""):
        return self.answer


@pytest.mark.parametrize(
    "answer,expected",
    [("y", True), ("n", False), ("Có", True), (" YES ", True), ("", False), ("no", False)],
)
def test_console_approver(answer, expected):
    approve = cli.console_approver(FakeConsole(answer))
    assert approve("write_note", {"title": "T", "content": "x" * 900}) is expected


@pytest.mark.parametrize("module", [cli, eval_mod])
def test_main_without_api_key_returns_1(monkeypatch, module):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(module, "load_dotenv", lambda *a, **k: None)
    assert module.main([]) == 1
