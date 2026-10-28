"""CLI parsing, API delegation and user-facing failure behavior."""

from unittest.mock import MagicMock, patch

import pytest

from bondi._cli import main


@pytest.fixture
def db():
    value = MagicMock()
    value.name = "demo"
    value.uri = "mongodb://127.0.0.1:27019/"
    value.status.return_value = "stopped"
    return value


def test_deploy_defaults_and_options(db, capsys):
    with patch("bondi._cli.deploy_mongodb", return_value=db) as deploy:
        assert main(["deploy", "mongodb"]) == 0
        deploy.assert_called_once_with("mongodb", port=27017, timeout=120)
        assert (
            main(["deploy", "mongodb", "--name", "demo", "--port", "27019", "--timeout", "300"])
            == 0
        )
        deploy.assert_called_with("demo", port=27019, timeout=300)
    assert db.uri in capsys.readouterr().out


@pytest.mark.parametrize("command", ["start", "stop"])
def test_lifecycle(db, command):
    with patch("bondi._cli.get_deployment", return_value=db) as get:
        assert main([command, "demo", "--timeout", "30"]) == 0
    get.assert_called_once_with("demo")
    getattr(db, command).assert_called_once_with(timeout=30)


@pytest.mark.parametrize("delete", [False, True])
def test_removal_is_explicit(db, delete, capsys):
    with patch("bondi._cli.get_deployment", return_value=db):
        assert main(["remove", "demo", "-y"] + ([] if delete else ["--keep-data"])) == 0
    db.remove.assert_called_once_with(delete_data=delete, timeout=120)
    assert ("deleted" if delete else "retained") in capsys.readouterr().out


def test_status_and_logs(db, capsys):
    with patch("bondi._cli.get_deployment", return_value=db):
        assert main(["status", "demo"]) == 0
        assert "demo: stopped" in capsys.readouterr().out
        db.logs.return_value = "MongoDB log\n"
        assert main(["logs", "demo", "--tail", "10"]) == 0
        db.logs.assert_called_once_with(tail=10)
        assert capsys.readouterr().out == "MongoDB log\n"


def test_list(db, capsys):
    with patch("bondi._cli.list_deployments", return_value=[]):
        assert main(["list"]) == 0
        assert "No saved deployments" in capsys.readouterr().out
    with patch("bondi._cli.list_deployments", return_value=[db]):
        assert main(["list"]) == 0
        assert "demo: stopped" in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("demo"),
        RuntimeError("Docker unavailable"),
        ValueError("invalid config"),
        PermissionError("access denied"),
    ],
)
def test_failures_are_nonzero_without_traceback(error, capsys):
    with patch("bondi._cli.get_deployment", side_effect=error):
        assert main(["status", "demo"]) == 1
    output = capsys.readouterr()
    assert "bondi:" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""


def test_interruption(capsys):
    with patch("bondi._cli.deploy_mongodb", side_effect=KeyboardInterrupt):
        assert main(["deploy", "mongodb"]) == 130
    assert "interrupted" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args", [[], ["stop"], ["deploy", "couchbase"], ["deploy", "mongodb", "--port", "oops"]]
)
def test_invalid_syntax(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "deploy" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["y", "yes", " YES "])
def test_removal_confirmation_accepts(db, answer):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", return_value=answer) as prompt,
    ):
        assert main(["remove", "demo"]) == 0
    assert "permanently delete" in prompt.call_args.args[0]
    db.remove.assert_called_once_with(delete_data=True, timeout=120)


@pytest.mark.parametrize("answer", ["", "n", "no", "anything"])
def test_removal_confirmation_declines(db, answer):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", return_value=answer),
    ):
        assert main(["remove", "demo"]) == 1
    db.remove.assert_not_called()


@pytest.mark.parametrize("error,code", [(EOFError(), 1), (KeyboardInterrupt(), 130)])
def test_removal_confirmation_interrupted(db, error, code):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", side_effect=error),
    ):
        assert main(["remove", "demo"]) == code
    db.remove.assert_not_called()


def test_keep_data_prompt(db):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", return_value="y") as prompt,
    ):
        assert main(["remove", "demo", "--keep-data"]) == 0
    assert "keeping its data" in prompt.call_args.args[0]
    db.remove.assert_called_once_with(delete_data=False, timeout=120)
