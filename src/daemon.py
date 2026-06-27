from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from time import perf_counter, sleep
from zoneinfo import ZoneInfo

import pandas as pd

from .agents.manager import AgentMode, ManagerRunConfig, OverallManager
from .config import LocalPaperConfig
from .database import get_store
from .market_calendar import NEW_YORK_TZ, get_us_market_session, now_new_york


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class DaemonConfig:
    """长期运行守护进程配置。"""

    mode: AgentMode = AgentMode.ONLINE
    loop_seconds: int = 900
    output_dir: Path = Path("outputs")
    log_dir: Path = Path("logs")
    status_file: str = "agent_status.json"
    stop_on_error: bool = False
    enable_online_scan: bool = True
    enable_weekly_research: bool = True


class AgentDaemon:
    """按时间调度 OverallManager 的本地 24 小时自动团队。"""

    def __init__(self, config: DaemonConfig | None = None) -> None:
        self.config = config or DaemonConfig()
        self.output_dir = self.config.output_dir
        self.log_dir = self.config.log_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.status_path = self.output_dir / self.config.status_file
        self.log_path = self.log_dir / "daemon.log"
        self.state = self._load_state()

    def run_forever(self) -> None:
        self._log("[START] AgentDaemon.run_forever started")
        while True:
            self.run_once()
            sleep(max(self.config.loop_seconds, 60))

    def run_once(self, force_job: str | None = None) -> list[dict[str, object]]:
        now_ny = now_new_york()
        jobs = self._due_jobs(now_ny, force_job)
        self._update_status("RUNNING", f"due_jobs={','.join(job['name'] for job in jobs) or 'none'}", now_ny)
        results: list[dict[str, object]] = []

        if not jobs:
            self._log("[IDLE] No daemon jobs are due")
            self._update_status("IDLE", "No jobs due", now_ny)
            return results

        for job in jobs:
            results.append(self._run_job(job, now_ny))

        self._update_status("IDLE", f"completed_jobs={len(results)}", now_ny)
        self._save_state()
        return results

    def _due_jobs(self, now_ny: datetime, force_job: str | None) -> list[dict[str, object]]:
        all_jobs = self._job_definitions(now_ny)
        if force_job:
            return [job for job in all_jobs if job["name"] == force_job]
        return [job for job in all_jobs if job["due"]]

    def _job_definitions(self, now_ny: datetime) -> list[dict[str, object]]:
        session = get_us_market_session(now_ny)
        after_close = bool(session.market_close and now_ny >= session.market_close + timedelta(minutes=20))
        trading_day_key = session.trading_day.isoformat()
        latest_completed_trading_day_key = self._latest_completed_trading_day_key(now_ny)
        local_account_day_key = self._local_paper_account_date()
        local_paper_run_key = latest_completed_trading_day_key or trading_day_key
        local_paper_needs_catchup = bool(
            local_paper_run_key and self._date_key_before(local_account_day_key, local_paper_run_key)
        )
        local_paper_due = bool(
            local_paper_run_key
            and not session.is_regular_hours
            and ((session.is_trading_day and after_close) or local_paper_needs_catchup)
            and self._last_key("daily_local_paper") != local_paper_run_key
        )
        day_key = now_ny.date().isoformat()
        week_key = f"{now_ny.isocalendar().year}-W{now_ny.isocalendar().week:02d}"

        return [
            {
                "name": "daily_local_paper",
                "due": local_paper_due,
                "run_key": local_paper_run_key,
                "mode": AgentMode.LOCAL,
                "run_local_paper": True,
                "run_research": False,
                "description": "美股收盘后或漏跑时补跑一次本地模拟盘和风控",
                "target_account_date": local_paper_run_key,
                "current_account_date": local_account_day_key,
            },
            {
                "name": "daily_risk_check",
                "due": self._last_key("daily_risk_check") != day_key,
                "run_key": day_key,
                "mode": AgentMode.LOCAL,
                "run_local_paper": False,
                "run_research": False,
                "description": "每日轻量风险检查",
            },
            {
                "name": "weekly_research",
                "due": self.config.enable_weekly_research
                and after_close
                and self._last_key("weekly_research") != week_key,
                "run_key": week_key,
                "mode": AgentMode.LOCAL,
                "run_local_paper": False,
                "run_research": True,
                "description": "每周刷新研究、回测健康度和自优化报告",
            },
            {
                "name": "daily_online_scan",
                "due": self.config.enable_online_scan
                and self.config.mode in {AgentMode.ONLINE, AgentMode.AI}
                and self._last_key("daily_online_scan") != day_key,
                "run_key": day_key,
                "mode": AgentMode.ONLINE if self.config.mode is AgentMode.ONLINE else AgentMode.AI,
                "run_local_paper": False,
                "run_research": False,
                "description": "每日联网公开项目扫描",
            },
        ]

    def _run_job(self, job: dict[str, object], now_ny: datetime) -> dict[str, object]:
        job_name = str(job["name"])
        start = perf_counter()
        self._log(f"[JOB] {job_name} started: {job['description']}")
        try:
            manager_config = ManagerRunConfig.for_mode(
                job["mode"],
                run_local_paper=bool(job["run_local_paper"]),
                run_research=bool(job["run_research"]),
                stop_on_error=self.config.stop_on_error,
            )
            agent_results = OverallManager(manager_config).run_once()
            hard_errors = [result for result in agent_results if result.status == "ERROR"]
            warnings = [result for result in agent_results if result.status == "WARN"]
            status = "ERROR" if hard_errors else "WARN" if warnings else "OK"
            message = f"agent_results={len(agent_results)} warnings={len(warnings)} errors={len(hard_errors)}"
            details = {
                "agents": [result.agent for result in agent_results],
                "warnings": [result.message for result in warnings],
                "errors": [result.message for result in hard_errors],
                "run_key": job["run_key"],
                "ny_time": now_ny.isoformat(),
            }
            record_success_key = status != "ERROR"
            if job_name == "daily_local_paper" and status != "ERROR":
                target_account_date = str(job.get("target_account_date") or job["run_key"])
                account_date_after_run = self._local_paper_account_date()
                details["target_account_date"] = target_account_date
                details["account_date_after_run"] = account_date_after_run
                if self._date_key_before(account_date_after_run, target_account_date):
                    status = "WARN"
                    record_success_key = False
                    catchup_message = (
                        "local paper account date did not reach target "
                        f"account_date={account_date_after_run or 'missing'} target={target_account_date}"
                    )
                    details.setdefault("warnings", []).append(catchup_message)
                    message = f"{message}; {catchup_message}"

            if record_success_key:
                self.state.setdefault("jobs", {}).setdefault(job_name, {})["last_run_key"] = job["run_key"]
                self.state["jobs"][job_name]["last_success_at"] = datetime.now(LOCAL_TZ).isoformat()
            self.state.setdefault("jobs", {}).setdefault(job_name, {})["last_status"] = status
            self.state["jobs"][job_name]["last_message"] = message
        except Exception as exc:
            status = "ERROR"
            message = f"{type(exc).__name__}: {exc}"
            details = {"traceback": traceback.format_exc(), "run_key": job.get("run_key", "")}
            self.state.setdefault("jobs", {}).setdefault(job_name, {})["last_status"] = status
            self.state["jobs"][job_name]["last_message"] = message

        elapsed = perf_counter() - start
        row = {
            "time": pd.Timestamp.now(),
            "job_name": job_name,
            "status": status,
            "mode": str(job["mode"].value if isinstance(job["mode"], AgentMode) else job["mode"]),
            "message": message,
            "elapsed_seconds": elapsed,
            "details_json": json.dumps(details, ensure_ascii=False),
        }
        get_store().append_frame("daemon_runs", pd.DataFrame([row]))
        self._log(f"[JOB] {job_name} {status}: {message} elapsed={elapsed:.1f}s")
        return row

    def _last_key(self, job_name: str) -> str:
        return str(self.state.get("jobs", {}).get(job_name, {}).get("last_run_key", ""))

    def _latest_completed_trading_day_key(self, now_ny: datetime) -> str:
        """返回当前时点之前已经完整收盘的最新美股交易日。"""
        session = get_us_market_session(now_ny)
        if session.is_trading_day and session.market_close and now_ny >= session.market_close + timedelta(minutes=20):
            return session.trading_day.isoformat()

        current_day = now_ny.date() - timedelta(days=1)
        for _ in range(14):
            probe = datetime.combine(current_day, time(12, 0), tzinfo=NEW_YORK_TZ)
            if get_us_market_session(probe).is_trading_day:
                return current_day.isoformat()
            current_day -= timedelta(days=1)
        return ""

    def _local_paper_account_date(self) -> str:
        path = self.output_dir / LocalPaperConfig().virtual_account_file
        if not path.exists() or path.stat().st_size == 0:
            return ""
        try:
            frame = pd.read_csv(path)
            if frame.empty or "as_of_date" not in frame.columns:
                return ""
            value = frame.iloc[-1]["as_of_date"]
            if pd.isna(value):
                return ""
            return pd.Timestamp(value).date().isoformat()
        except Exception:
            return ""

    @staticmethod
    def _date_key_before(current_key: str, target_key: str) -> bool:
        if not target_key:
            return False
        if not current_key:
            return True
        return current_key < target_key

    def _load_state(self) -> dict[str, object]:
        if not self.status_path.exists() or self.status_path.stat().st_size == 0:
            return {"status": "NEW", "jobs": {}}
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except Exception:
            return {"status": "RECOVERED_FROM_BAD_STATE", "jobs": {}}

    def _save_state(self) -> None:
        self.state["updated_at"] = datetime.now(LOCAL_TZ).isoformat()
        self.status_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update_status(self, status: str, message: str, now_ny: datetime) -> None:
        session = get_us_market_session(now_ny)
        self.state.update(
            {
                "status": status,
                "message": message,
                "local_time": datetime.now(LOCAL_TZ).isoformat(),
                "new_york_time": now_ny.isoformat(),
                "market": {
                    "trading_day": session.trading_day.isoformat(),
                    "is_trading_day": session.is_trading_day,
                    "is_regular_hours": session.is_regular_hours,
                    "market_open": session.market_open.isoformat() if session.market_open else None,
                    "market_close": session.market_close.isoformat() if session.market_close else None,
                    "source": session.source,
                },
            }
        )
        self._save_state()

    def _log(self, message: str) -> None:
        line = f"{datetime.now(LOCAL_TZ).isoformat()} {message}"
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
