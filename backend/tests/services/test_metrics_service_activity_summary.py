from app.services.metrics_service import MetricsService


class _BugQuery:
    def join(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def group_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return []


class _ScalarQuery:
    def join(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def scalar(self):  # type: ignore[no-untyped-def]
        return 0


class _DBStub:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        self.calls += 1
        if self.calls == 1:
            return _BugQuery()
        if self.calls in {2, 3}:
            return _ScalarQuery()
        raise AssertionError(f"Unexpected query call index: {self.calls}")


class _UsageServiceStub:
    @staticmethod
    def get_summary(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return {
            "active_users_last_n_days": 5,
            "messages_last_n_days": 20,
            "approx_avg_response_secs": 1.25,
        }


def test_get_metrics_includes_branching_rates_and_user_messages_submitted(monkeypatch) -> None:
    service = MetricsService(usage_service=_UsageServiceStub())
    db = _DBStub()

    monkeypatch.setattr(
        service,
        "_feedback_counts",
        lambda db, include_admins, start_db=None, end_exclusive_db=None: (  # type: ignore[no-untyped-def]
            {"total": 10, "up": 7, "down": 3, "time_saved_minutes": 70, "time_spent_minutes": 15}
            if start_db is None and end_exclusive_db is None
            else {"total": 4, "up": 3, "down": 1, "time_saved_minutes": 30, "time_spent_minutes": 5}
        ),
    )
    monkeypatch.setattr(
        service,
        "_activity_counts",
        lambda db, scope, start_day=None, end_day=None: (  # type: ignore[no-untyped-def]
            {
                "share_imported": 8,
                "conversation_branched": 84,
                "conversation_compacted": 30,
                "project_created": 12,
                "group_joined": 40,
                "user_message_submitted": 420,
                "output_applied_to_live_work": 15,
                "output_deployed_to_live_work": 10,
                "redaction_entry_created": 50,
                "redaction_applied": 80,
            }
            if start_day is None and end_day is None
            else (
                {
                    "share_imported": 3,
                    "conversation_branched": 30,
                    "conversation_compacted": 8,
                    "project_created": 4,
                    "group_joined": 7,
                    "user_message_submitted": 200,
                    "output_applied_to_live_work": 5,
                    "output_deployed_to_live_work": 3,
                    "redaction_entry_created": 11,
                    "redaction_applied": 17,
                }
                if ((end_day - start_day).days + 1) == 30
                else {
                    "share_imported": 1,
                    "conversation_branched": 7,
                    "conversation_compacted": 1,
                    "project_created": 1,
                    "group_joined": 1,
                    "user_message_submitted": 35,
                    "output_applied_to_live_work": 4,
                    "output_deployed_to_live_work": 2,
                    "redaction_entry_created": 2,
                    "redaction_applied": 3,
                }
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_count_distinct_users_with_activity",
        lambda db, activity_type, include_admins, start_db=None, end_exclusive_db=None: (  # type: ignore[no-untyped-def]
            3 if activity_type == "conversation_branched" else 4
        ),
    )
    monkeypatch.setattr(
        service,
        "_active_conversation_count_from_runs",
        lambda db, include_admins, start_db, end_exclusive_db: 20,  # type: ignore[no-untyped-def]
    )
    monkeypatch.setattr(
        service,
        "_run_outcome_metrics",
        lambda db, include_admins, start_db, end_exclusive_db: {  # type: ignore[no-untyped-def]
            "runs_started_last_n_days": 100,
            "runs_completed_last_n_days": 82,
            "runs_failed_last_n_days": 12,
            "runs_cancelled_last_n_days": 6,
            "run_completion_rate_last_n_days": 0.82,
            "run_failure_rate_last_n_days": 0.12,
            "run_cancel_rate_last_n_days": 0.06,
            "failed_or_cancelled_runs_last_n_days": 18,
            "recovered_failed_or_cancelled_runs_last_n_days": 9,
            "failure_recovery_rate_last_n_days": 0.5,
        },
    )
    monkeypatch.setattr(
        service,
        "_count_distinct_users_with_activity_types",
        lambda db, activity_types, include_admins, start_db=None, end_exclusive_db=None: 2,  # type: ignore[no-untyped-def]
    )
    monkeypatch.setattr(
        service,
        "_count_distinct_users_with_group_usage",
        lambda db, include_admins, start_db, end_exclusive_db: 4,  # type: ignore[no-untyped-def]
    )
    result = service.get_metrics(
        db=db,  # type: ignore[arg-type]
        days=7,
        include_admins=False,
    )

    assert result["feature_adoption"]["totals"]["user_messages_submitted"] == 420
    assert result["feature_adoption"]["last_n_days"]["user_messages_submitted"] == 35
    assert result["collaboration"]["totals"]["shares_created"] == 0
    assert result["collaboration"]["totals"]["shares_imported"] == 8
    assert result["collaboration"]["totals"]["projects_created"] == 12
    assert result["collaboration"]["totals"]["members_joined"] == 40
    assert result["collaboration"]["last_n_days"]["collaboration_events"] == 3
    assert result["collaboration"]["users_with_share_activity_last_n_days"] == 2
    assert result["collaboration"]["users_with_group_usage_last_n_days"] == 4
    assert result["collaboration"]["share_activity_rate_last_n_days"] == 0.4
    assert result["collaboration"]["group_usage_rate_last_n_days"] == 0.8
    assert result["collaboration"]["collaboration_events_per_active_user_last_n_days"] == 0.6
    assert result["branching"]["branch_rate_last_n_days"] == 0.2
    assert result["branching"]["users_branched_last_n_days"] == 3
    assert result["branching"]["message_active_users_last_n_days"] == 4
    assert result["branching"]["users_branched_rate_last_n_days"] == 0.75
    assert result["branching"]["branch_rate_7d"] == 0.2
    assert result["branching"]["branch_rate_30d"] == 0.15
    assert result["real_world_application"]["totals"]["outputs_applied_to_live_work"] == 15
    assert result["real_world_application"]["totals"]["outputs_deployed_to_live_work"] == 10
    assert result["real_world_application"]["last_n_days"]["outputs_applied_to_live_work"] == 4
    assert result["real_world_application"]["last_n_days"]["outputs_deployed_to_live_work"] == 2
    assert result["real_world_application"]["users_with_output_applied_last_n_days"] == 2
    assert result["real_world_application"]["users_with_output_deployed_last_n_days"] == 2
    assert result["real_world_application"]["output_applied_rate_last_n_days"] == 0.5
    assert result["real_world_application"]["output_deployed_rate_last_n_days"] == 0.5
    assert result["real_world_application"]["output_deployment_conversion_last_n_days"] == 0.5
    assert result["adaptability"]["active_conversations_last_n_days"] == 20
    assert result["adaptability"]["avg_user_messages_per_active_conversation_last_n_days"] == 1.75
    assert result["adaptability"]["run_completion_rate_last_n_days"] == 0.82
    assert result["adaptability"]["failure_recovery_rate_last_n_days"] == 0.5
    assert "tool_diversity" not in result
