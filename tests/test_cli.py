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
        assert main(["deployment", "create", "mongodb"]) == 0
        deploy.assert_called_once_with(
            "mongodb",
            port=27017,
            version=None,
            timeout=120,
            memory_limit_mb=None,
            wiredtiger_cache_size_gb=None,
        )
        assert (
            main(
                [
                    "deployment",
                    "create",
                    "mongodb",
                    "--name",
                    "demo",
                    "--port",
                    "27019",
                    "--timeout",
                    "300",
                ]
            )
            == 0
        )
        deploy.assert_called_with(
            "demo",
            port=27019,
            version=None,
            timeout=300,
            memory_limit_mb=None,
            wiredtiger_cache_size_gb=None,
        )
    output = capsys.readouterr().out
    assert db.uri in output
    assert f'mongosh "{db.uri}"' in output
    assert "mongoimport" in output and "mongorestore" in output
    assert "https://www.mongodb.com/docs/database-tools/installation/" in output


@pytest.mark.parametrize("command", ["start", "stop"])
def test_lifecycle(db, command):
    with patch("bondi._cli.get_deployment", return_value=db) as get:
        assert main(["deployment", command, "demo", "--timeout", "30"]) == 0
    get.assert_called_once_with("demo")
    getattr(db, command).assert_called_once_with(timeout=30)


@pytest.mark.parametrize("delete", [False, True])
def test_removal_is_explicit(db, delete, capsys):
    with patch("bondi._cli.get_deployment", return_value=db):
        assert (
            main(["deployment", "remove", "demo", "-y"] + ([] if delete else ["--keep-data"])) == 0
        )
    db.remove.assert_called_once_with(keep_data=not delete, timeout=120)
    assert ("deleted" if delete else "retained") in capsys.readouterr().out


def test_status_and_logs(db, capsys):
    with patch("bondi._cli.get_deployment", return_value=db):
        assert main(["deployment", "status", "demo"]) == 0
        assert "demo: stopped" in capsys.readouterr().out
        db.logs.return_value = "MongoDB log\n"
        assert main(["deployment", "logs", "demo", "--tail", "10"]) == 0
        db.logs.assert_called_once_with(tail=10)
        assert capsys.readouterr().out == "MongoDB log\n"


def test_list(db, capsys):
    with patch("bondi._cli.list_deployments", return_value=[]):
        assert main(["deployment", "list"]) == 0
        assert "No saved deployments" in capsys.readouterr().out
    with patch("bondi._cli.list_deployments", return_value=[db]):
        assert main(["deployment", "list"]) == 0
        output = capsys.readouterr().out
        assert all(value in output for value in ("Name", "Status", "demo", "stopped", db.uri))


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
        assert main(["deployment", "status", "demo"]) == 1
    output = capsys.readouterr()
    assert "bondi:" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""


def test_interruption(capsys):
    with patch("bondi._cli.deploy_mongodb", side_effect=KeyboardInterrupt):
        assert main(["deployment", "create", "mongodb"]) == 130
    assert "interrupted" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["deployment", "stop"],
        ["deployment", "create", "unknown"],
        ["deployment", "create", "mongodb", "--port", "oops"],
    ],
)
def test_invalid_syntax(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_help(capsys):
    assert main(["--help"]) == 0
    assert "deployment" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["y", "yes", " YES "])
def test_removal_confirmation_accepts(db, answer):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", return_value=answer) as prompt,
    ):
        assert main(["deployment", "remove", "demo"]) == 0
    assert "permanently delete" in prompt.call_args.args[0]
    db.remove.assert_called_once_with(keep_data=False, timeout=120)


@pytest.mark.parametrize("answer", ["", "n", "no", "anything"])
def test_removal_confirmation_declines(db, answer):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", return_value=answer),
    ):
        assert main(["deployment", "remove", "demo"]) == 1
    db.remove.assert_not_called()


@pytest.mark.parametrize("error,code", [(EOFError(), 1), (KeyboardInterrupt(), 130)])
def test_removal_confirmation_interrupted(db, error, code):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", side_effect=error),
    ):
        assert main(["deployment", "remove", "demo"]) == code
    db.remove.assert_not_called()


def test_keep_data_prompt(db):
    with (
        patch("bondi._cli.get_deployment", return_value=db),
        patch("builtins.input", return_value="y") as prompt,
    ):
        assert main(["deployment", "remove", "demo", "--keep-data"]) == 0
    assert "keeping its data" in prompt.call_args.args[0]
    db.remove.assert_called_once_with(keep_data=True, timeout=120)


def test_click_couchbase_options_and_secret(db, monkeypatch):
    from click.testing import CliRunner

    from bondi._cli import cli

    monkeypatch.setenv("CB_SECRET", "private-password")
    with patch("bondi._cli.deploy_couchbase", return_value=db) as deploy:
        result = CliRunner().invoke(
            cli,
            [
                "deployment",
                "create",
                "couchbase",
                "--name",
                "cb",
                "--management-port",
                "18091",
                "--query-port",
                "18093",
                "--kv-port",
                "11211",
                "--edition",
                "enterprise",
                "--version",
                "8.0.0",
                "--username",
                "research",
                "--password-env",
                "CB_SECRET",
                "--bucket",
                "travel",
                "--memory-limit-mb",
                "8192",
                "--timeout",
                "90",
            ],
        )
    assert result.exit_code == 0, result.output
    deploy.assert_called_once_with(
        "cb",
        management_port=18091,
        query_port=18093,
        kv_port=11211,
        edition="enterprise",
        version="8.0.0",
        username="research",
        password="private-password",
        bucket="travel",
        memory_limit_mb=8192,
        timeout=90,
    )
    assert "private-password" not in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["dataset", "load-file", "demo.jsonl", "--collection", "items"],
        [
            "dataset",
            "load-file",
            "demo.jsonl",
            "--collection",
            "items",
            "--deployment",
            "a",
            "--connection",
            "b",
        ],
        [
            "dataset",
            "load-file",
            "demo.jsonl",
            "--collection",
            "items",
            "--deployment",
            "a",
            "--mode",
            "invalid",
        ],
        ["dataset"],
        ["deployment", "create"],
        ["deployment", "stop", "a", "--unknown"],
    ],
)
def test_click_invalid_options(args):
    from click.testing import CliRunner

    from bondi._cli import cli

    with patch("bondi._cli.get_deployment") as get:
        result = CliRunner().invoke(cli, args)
    assert result.exit_code == 2
    get.assert_not_called()


def test_click_operation_failure_exit_code():
    from click.testing import CliRunner

    from bondi._cli import cli

    with patch("bondi._cli.get_deployment", side_effect=RuntimeError("unavailable")):
        result = CliRunner().invoke(cli, ["deployment", "status", "missing"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "unavailable" in result.stderr


def test_click_hf_options(monkeypatch):
    from types import SimpleNamespace

    from click.testing import CliRunner

    from bondi._cli import cli

    captured = {}
    monkeypatch.setattr("bondi.data._cli.run", lambda args: captured.update(vars(args)))
    result = CliRunner().invoke(
        cli,
        [
            "dataset",
            "load-hf",
            "org/repo",
            "--dataset",
            "users",
            "--deployment",
            "db",
            "--database",
            "travel",
            "--collection",
            "items",
            "--split",
            "train",
            "--split",
            "test",
            "--mode",
            "replace",
            "--revision",
            "v1",
            "--namespace",
            "test",
            "--id-field",
            "key",
        ],
    )
    assert result.exit_code == 0, result.output
    args = SimpleNamespace(**captured)
    assert args.source == "org/repo" and args.dataset == "users"
    assert args.split == ["train", "test"]
    assert args.collection == "items" and args.database == "travel"
    assert args.mode == "replace" and args.revision == "v1"
    assert args.namespace == "test" and args.id_field == "key"


def test_terminal_values_are_literal_and_redirected_output_has_no_ansi(db):
    from click.testing import CliRunner

    from bondi._cli import cli

    db.name = "[red]literal[/red]"
    with patch("bondi._cli.list_deployments", return_value=[db]):
        result = CliRunner().invoke(cli, ["deployment", "list"])
    assert result.exit_code == 0
    assert db.name in result.output
    assert "\x1b[" not in result.output


def test_raw_logs_preserve_markup_and_newlines(db):
    from click.testing import CliRunner

    from bondi._cli import cli

    db.logs.return_value = "[red]raw[/red]\n\x1b[31mlast line\x1b[0m"
    with patch("bondi._cli.get_deployment", return_value=db):
        result = CliRunner().invoke(cli, ["deployment", "logs", "demo"])
    assert result.output == db.logs.return_value


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["deployment", "create"],
        ["deployment", "create", "mongodb"],
        ["deployment", "create", "couchbase"],
        ["dataset"],
        ["dataset", "load-file"],
        ["dataset", "list"],
        ["dataset", "info"],
        ["deployment", "remove"],
    ],
)
def test_command_help(args):
    from click.testing import CliRunner

    from bondi._cli import cli

    result = CliRunner().invoke(cli, [*args, "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


@pytest.mark.parametrize("command", ["list", "status"])
@pytest.mark.parametrize("retained", [True, False])
def test_removed_volume_label(db, command, retained, capsys):
    db.status.return_value = "removed"
    db._data_volume_exists.return_value = retained
    with (
        patch("bondi._cli.list_deployments", return_value=[db]),
        patch("bondi._cli.get_deployment", return_value=db),
    ):
        assert main(["deployment", command] + (["demo"] if command == "status" else [])) == 0
    output = capsys.readouterr().out
    assert "removed" in output
    assert ("data retained" in output) == retained
    db._data_volume_exists.assert_called_once()


@pytest.mark.parametrize(
    "state,code",
    [
        ("unhealthy", "31"),
        ("removed", "2;90"),
        ("removed (data retained)", "2;90"),
    ],
)
def test_status_colours(state, code):
    from io import StringIO

    from rich.console import Console

    from bondi import _terminal

    output = StringIO()
    terminal = Console(
        file=output, force_terminal=True, color_system="standard", no_color=False, width=120
    )
    with patch("bondi._terminal.console", return_value=terminal):
        _terminal.status("demo", state, "uri")
        _terminal.table("Deployments", ["Status"], [[state]])
    assert output.getvalue().count(f"\x1b[{code}m{state}") == 2


def test_cli_command_groups():
    from bondi._cli import cli

    assert set(cli.commands) == {"dataset", "deployment"}
    assert set(cli.commands["deployment"].commands) == {
        "create",
        "list",
        "logs",
        "remove",
        "start",
        "status",
        "stop",
        "load-demo-data",
    }
    assert set(cli.commands["deployment"].commands["create"].commands) == {"mongodb", "couchbase"}


@pytest.mark.parametrize(
    "command", ["datasets", "deploy", "list", "logs", "remove", "start", "status", "stop"]
)
def test_old_root_commands_are_rejected(command):
    from click.testing import CliRunner

    from bondi._cli import cli

    result = CliRunner().invoke(cli, [command])
    assert result.exit_code == 2
    assert "No such command" in result.output
