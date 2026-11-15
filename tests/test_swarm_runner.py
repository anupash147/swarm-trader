from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

import run_hedge_fund as runner


def test_execution_time_requires_timezone():
    with pytest.raises(runner.argparse.ArgumentTypeError):
        runner._execution_time("2026-11-16T09:30:00")
    assert runner._execution_time("2026-11-16T09:30:00-06:00").utcoffset() == timedelta(hours=-6)


@pytest.mark.parametrize("market_open", [True, False])
def test_wait_checks_paper_market_before_execution(market_open):
    target = datetime(2026, 11, 16, 15, 30, tzinfo=timezone.utc)
    response = Mock()
    response.json.return_value = {"is_open": market_open}
    with patch.object(runner, "datetime") as clock, patch.object(runner.time, "sleep") as wait, patch.object(runner.requests, "get", return_value=response) as get, patch("src.accounts.get_account_for_mode", return_value=Mock(headers={})) as account:
        clock.now.side_effect = [target - timedelta(seconds=10), target]
        if market_open:
            runner._wait_for_execution(target, 300, "day")
        else:
            with pytest.raises(RuntimeError, match="Market is closed"):
                runner._wait_for_execution(target, 300, "day")
        wait.assert_called_once_with(10)
        account.assert_called_once_with("day")
        assert get.call_args.args[0] == "https://paper-api.alpaca.markets/v2/clock"


def test_late_execution_never_contacts_broker():
    target = datetime(2026, 11, 16, 15, 30, tzinfo=timezone.utc)
    with patch.object(runner, "datetime") as clock, patch.object(runner.requests, "get") as get:
        clock.now.return_value = target + timedelta(seconds=301)
        with pytest.raises(RuntimeError, match="deadline missed"):
            runner._wait_for_execution(target, 300, "swing")
        get.assert_not_called()


def test_executor_failure_is_not_reported_as_success():
    with patch.object(runner.subprocess, "run", return_value=Mock(returncode=1, stderr="", stdout="")):
        with pytest.raises(RuntimeError, match="Trade executor failed"):
            runner._execute_via_execute_trades({"NVDA": {"action": "buy", "quantity": 1}}, "swing", True)


def test_analysis_is_retained_when_deadline_is_missed(tmp_path):
    output = tmp_path / "results.json"
    decisions = {"NVDA": {"action": "hold", "quantity": 0}}
    with patch.object(runner.sys, "argv", ["swarm", "--mode", "swing", "--tickers", "NVDA", "--execute", "--execute-at", "2026-11-16T09:30:00-06:00", "--output", str(output)]), patch.object(runner, "get_alpaca_account", return_value={}), patch.object(runner, "get_alpaca_positions", return_value=[]), patch.object(runner, "format_positions_summary", return_value=""), patch.object(runner, "convert_to_portfolio", return_value={}), patch.object(runner, "run_hedge_fund", return_value={"decisions": decisions}), patch.object(runner, "_wait_for_execution", side_effect=RuntimeError("Execution deadline missed")), patch.object(runner, "_execute_via_execute_trades") as execute:
        assert runner.main() == 1
        assert runner.json.loads(output.read_text())["decisions"] == decisions
        execute.assert_not_called()