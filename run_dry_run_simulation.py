"""
DRY-RUN LIFECYCLE SIMULATION HARNESS (PHASE 2)
==============================================================================
Simulates a full trading day lifecycle (09:00 -> 09:15 -> 15:25 -> 15:30 -> 15:35)
to prove that the health monitoring safety net, report generation, and emergency
kill-switch operate reliably before committing to full-week forward testing.
==============================================================================
"""

import sys
import json
import time
import logging
from datetime import datetime

import system_health_monitor as health_monitor
import system_control

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] %(message)s")
logger = logging.getLogger("DryRunHarness")


def run_full_dry_run_simulation() -> bool:
    logger.info("======================================================================")
    logger.info("🚀 STARTING DRY-RUN SIMULATION (PHASE 2 READINESS VERIFICATION)")
    logger.info("======================================================================")

    # 1. Simulate process startup / cold start
    logger.info("\n--- STEP 1: Process Startup & Cold-Start Logging ---")
    health_monitor.log_cold_start({"simulation": True, "type": "DRY_RUN_TEST"})
    summary = health_monitor.get_system_health_summary()
    logger.info(f"Health summary after startup: Score={summary['score']}, Status={summary['status']}")
    assert summary["score"] == 100, f"Expected 100 score on clean start, got {summary['score']}"

    # 2. Simulate Pre-market -> Market Open transition
    logger.info("\n--- STEP 2: Market Open State Transition ---")
    health_monitor.log_market_transition("PRE_MARKET", "OPEN", mode="LIVE 5-PILLAR SCANNING")
    summary = health_monitor.get_system_health_summary()
    logger.info(f"Transitions logged: {len(summary['recent_transitions'])}")

    # 3. Simulate 9:15 AM Evaluation run
    logger.info("\n--- STEP 3: 9:15 AM Evaluation Event Simulation ---")
    mock_graded = 6
    mock_wins = 5
    mock_losses = 1
    mock_win_rate = 83.3
    health_monitor.log_evaluation_event(
        evaluated_count=mock_graded,
        wins=mock_wins,
        losses=mock_losses,
        win_rate_pct=mock_win_rate,
        details={"mock": True, "notes": "Dry run gap evaluation"}
    )
    summary = health_monitor.get_system_health_summary()
    logger.info(f"Last evaluation logged: {summary['last_evaluation']['evaluated_count']} graded, {summary['last_evaluation']['win_rate_pct']}% win rate")
    assert summary["last_evaluation"]["evaluated_count"] == mock_graded

    # 4. Simulate 3:25 PM Auto-lock and 3:30 PM Final Lock
    logger.info("\n--- STEP 4: 3:30 PM Lock Event Simulation ---")
    mock_locked_symbols = ["RELIANCE", "TCS", "INFY", "BHARTIARTL", "HDFCBANK"]
    health_monitor.log_lock_event(
        lock_type="BTST_330_LOCK",
        locked_count=len(mock_locked_symbols),
        symbols=mock_locked_symbols,
        details={"mock": True}
    )
    summary = health_monitor.get_system_health_summary()
    logger.info(f"Last lock logged: {summary['last_lock']['locked_count']} picks ({summary['last_lock']['symbols']})")
    assert summary["last_lock"]["locked_count"] == len(mock_locked_symbols)

    # 5. Simulate Market Close Transition
    logger.info("\n--- STEP 5: Market Close State Transition ---")
    health_monitor.log_market_transition("OPEN", "CLOSED", mode="OFF-MARKET SNAPSHOT (3:30 PM Scan Locked)")

    # 6. Test Emergency Kill Switch (Pause -> Check -> Resume)
    logger.info("\n--- STEP 6: Emergency Kill-Switch Verification ---")
    assert not system_control.is_system_paused()
    
    pause_state = system_control.pause_system(reason="Dry Run Emergency Test", paused_by="Tester")
    assert system_control.is_system_paused()
    logger.info(f"Kill switch active: {pause_state['is_paused']} (Reason: {pause_state['pause_reason']})")
    
    resume_state = system_control.resume_system(resumed_by="Tester")
    assert not system_control.is_system_paused()
    logger.info(f"System resumed: is_paused={resume_state['is_paused']}")

    # 7. Generate Daily Health Report and Verify Archive
    logger.info("\n--- STEP 7: Daily Health Report Generation ---")
    today_str = health_monitor._get_today_date_str()
    report = health_monitor.generate_daily_health_report(today_str)
    
    logger.info(f"Daily Health Report Generated for {report['date']}:")
    logger.info(f" - Health Score: {report['health_score']}/100 ({report['status']})")
    logger.info(f" - Evaluations Logged: {len(report['milestones']['evaluations'])}")
    logger.info(f" - Locks Logged: {len(report['milestones']['locks'])}")
    logger.info(f" - Transitions Count: {report['milestones']['transitions_count']}")
    logger.info(f" - Issues Detected: {report['issues']}")
    
    assert report["health_score"] == 100
    assert report["status"] == "NOMINAL"
    assert len(report["milestones"]["evaluations"]) >= 1
    assert len(report["milestones"]["locks"]) >= 1

    # 8. Test Anomaly Detection Capability (Inject mock error and verify score drops)
    logger.info("\n--- STEP 8: Anomaly & Exception Detection Test ---")
    health_monitor.log_system_error("SIMULATION_TEST", "Test artificial exception to verify safety net detection")
    anom_summary = health_monitor.get_system_health_summary()
    logger.info(f"Health score after error injection: {anom_summary['score']}/100")
    logger.info(f"Issues detected: {anom_summary['issues']}")
    assert anom_summary["score"] < 100
    assert len(anom_summary["issues"]) > 0
    logger.info("Anomaly detection confirmed: Safety net caught the error and penalized score accurately!")

    logger.info("\n======================================================================")
    logger.info("✅ ALL DRY-RUN SIMULATION TESTS PASSED (100% OPERATIONAL READINESS)")
    logger.info("======================================================================")
    return True


if __name__ == "__main__":
    success = run_full_dry_run_simulation()
    sys.exit(0 if success else 1)
