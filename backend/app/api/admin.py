from decimal import Decimal
from datetime import datetime, timezone, date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, case
from typing import Optional


def _parse_date(d: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD string to date object."""
    if not d:
        return None
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_date_range(
    start_date: Optional[str],
    end_date: Optional[str],
    days: int,
) -> tuple[date, date]:
    """
    Resolve start and end dates from parameters.

    If start_date and end_date are provided, use them.
    Otherwise, calculate from days parameter (ending today).
    """
    today = datetime.now(timezone.utc).date()

    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)

    if parsed_start and parsed_end:
        # Ensure start <= end
        if parsed_start > parsed_end:
            parsed_start, parsed_end = parsed_end, parsed_start
        # Cap end date to today
        if parsed_end > today:
            parsed_end = today
        return parsed_start, parsed_end

    # Fall back to days-based calculation
    return today - timedelta(days=days - 1), today

from ..auth.dependencies import admin_required, get_current_user
from ..config.database import get_db
from ..schemas.admin import (
    UsersPage,
    UserAdmin,
    UserLookupItem,
    UserLookupResponse,
    RoleUpdate,
    ActiveUpdate,
    TierUpdate,
    ModelOverrideUpdate,
)
from ..schemas.usage import UsageSummary
from ..schemas.admin_settings import ChatProviderResponse, ChatProviderUpdate
from ..schemas.admin_metrics import (
    BugMetrics,
    TimeSavingsInsights,
    OverviewSummary,
    ToolsDistributionSummary,
    SectorDistributionSummary,
)
from ..services.admin import AdminService
from ..services.admin.sector_classification_service import (
    get_sector_distribution as build_sector_distribution,
)
from ..services.usage_service import UsageService
from ..services.metrics_service import MetricsService
from ..database.models import (
    AdminUserRollup,
    AppSetting,
    User,
)
from ..services.chat_provider_service import (
    chat_model_options,
    ensure_provider_is_configured,
    invalidate_provider_cache,
    provider_for_model,
    resolve_chat_provider,
    validate_chat_model,
)
from ..services.provider_costs import format_cost
from ..utils.roles import non_admin_role_filter
from ..utils.timezone_context import DEFAULT_REPORTING_TIMEZONE
from ..utils.datetime_helpers import format_utc_z


router = APIRouter(prefix="/admin", tags=["admin"])
service = AdminService()
usage_service = UsageService()
metrics_service = MetricsService(usage_service=usage_service)


def _get_user_stats(db: Session, user: User) -> tuple[int, Decimal]:
    """Get conversation count and total cost for a user from rollup."""
    row = (
        db.query(
            func.coalesce(AdminUserRollup.conversation_count, 0),
            func.coalesce(AdminUserRollup.total_cost_usd, 0),
        )
        .filter(AdminUserRollup.user_id == user.id)
        .first()
    )
    if row is not None:
        return int(row[0] or 0), Decimal(str(row[1] or 0))
    return 0, Decimal("0")


def _build_user_admin_response(user: User, conversation_count: int, total_cost: Decimal) -> UserAdmin:
    """Build a UserAdmin response object."""
    return UserAdmin(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role or "user",
        user_tier=user.user_tier or "default",
        model_override=user.model_override,
        is_active=bool(user.is_active),
        created_at=user.created_at.isoformat() if user.created_at else "",
        last_login_at=format_utc_z(user.last_login_at),
        conversation_count=conversation_count,
        total_cost_usd=format_cost(total_cost, digits=4),
    )


@router.get("/users", response_model=UsersPage, dependencies=[Depends(admin_required)])
def list_users(
    search: Optional[str] = Query(None, description="Search by email or name"),
    include_admins: bool = Query(True, description="Include admin users. Default true."),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: Optional[str] = Query(None, description="Sort by: last_login_at, conversation_count, total_cost_usd"),
    sort_dir: str = Query("desc", description="Sort direction: asc or desc"),
    db: Session = Depends(get_db),
):
    total, users = service.list_users(
        db=db,
        search=search,
        include_admins=include_admins,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    items = [
        _build_user_admin_response(
            user=user,
            conversation_count=int(conversation_count or 0),
            total_cost=Decimal(str(total_cost or 0)),
        )
        for user, conversation_count, total_cost in users
    ]
    return UsersPage(total=total, page=page, page_size=page_size, items=items)


@router.get("/users/lookup", response_model=UserLookupResponse, dependencies=[Depends(admin_required)])
def lookup_users(
    search: str = Query(..., description="Search by email or name"),
    include_admins: bool = Query(True, description="Include admin users in lookup. Default true."),
    limit: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_db),
):
    normalized_search = search.strip()
    if not normalized_search:
        return UserLookupResponse(items=[])

    like = f"%{normalized_search}%"
    query = db.query(User).filter(or_(User.email.ilike(like), User.name.ilike(like)))
    if not include_admins:
        query = query.filter(non_admin_role_filter(User.role))

    users = query.order_by(
        case((User.last_login_at.is_(None), 1), else_=0).asc(),
        User.last_login_at.desc(),
        User.email.asc(),
    ).limit(limit).all()
    return UserLookupResponse(
        items=[
            UserLookupItem(
                id=str(user.id),
                email=user.email,
                name=user.name,
                role="admin" if str(user.role or "").strip().lower() == "admin" else "user",
            )
            for user in users
        ]
    )


@router.patch("/users/{user_id}/role", response_model=UserAdmin, dependencies=[Depends(admin_required)])
def change_user_role(
    user_id: str,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    acting_user: User = Depends(get_current_user),
):
    try:
        user = service.update_user_role(
            db=db, target_user_id=user_id, new_role=payload.role, acting_user=acting_user
        )
        conversation_count, total_cost = _get_user_stats(db, user)
        return _build_user_admin_response(user, conversation_count, total_cost)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/users/{user_id}/active", response_model=UserAdmin, dependencies=[Depends(admin_required)])
def change_user_active(
    user_id: str,
    payload: ActiveUpdate,
    db: Session = Depends(get_db),
    acting_user: User = Depends(get_current_user),
):
    try:
        user = service.update_user_active(
            db=db,
            target_user_id=user_id,
            is_active=payload.is_active,
            acting_user=acting_user,
        )
        conversation_count, total_cost = _get_user_stats(db, user)
        return _build_user_admin_response(user, conversation_count, total_cost)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/users/{user_id}/tier", response_model=UserAdmin, dependencies=[Depends(admin_required)])
def change_user_tier(
    user_id: str,
    payload: TierUpdate,
    db: Session = Depends(get_db),
    acting_user: User = Depends(get_current_user),
):
    """Update a user's tier (default or power)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.user_tier = payload.tier
    db.commit()
    db.refresh(user)

    conversation_count, total_cost = _get_user_stats(db, user)
    return _build_user_admin_response(user, conversation_count, total_cost)


@router.patch("/users/{user_id}/model", response_model=UserAdmin, dependencies=[Depends(admin_required)])
def change_user_model_override(
    user_id: str,
    payload: ModelOverrideUpdate,
    db: Session = Depends(get_db),
):
    """Set or clear a per-user model override."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.model is None:
        user.model_override = None
    else:
        try:
            normalized_model = validate_chat_model(payload.model)
            ensure_provider_is_configured(provider_for_model(normalized_model))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        user.model_override = normalized_model

    db.commit()
    db.refresh(user)

    conversation_count, total_cost = _get_user_stats(db, user)
    return _build_user_admin_response(user, conversation_count, total_cost)


@router.get("/usage", response_model=UsageSummary, dependencies=[Depends(admin_required)])
def get_usage(
    days: int = Query(30, description="Number of days to summarise (used if start_date/end_date not provided)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD). Overrides days param."),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD). Overrides days param."),
    include_admins: bool = Query(
        False,
        description="Include admin users in usage aggregates. Default false (exclude admins).",
    ),
    db: Session = Depends(get_db),
):
    resolved_start, resolved_end = _resolve_date_range(start_date, end_date, days)
    # Calculate effective days from resolved range
    effective_days = (resolved_end - resolved_start).days + 1

    # Range metrics are live from aggregates; global totals are served from
    # a bounded-staleness snapshot to keep this endpoint scalable.
    summary = usage_service.get_summary(
        db=db,
        days=effective_days,
        include_admins=include_admins,
        start_date=resolved_start,
        end_date=resolved_end,
        include_extended=False,
    )
    return UsageSummary(**summary)


@router.get("/analytics/bugs", response_model=BugMetrics, dependencies=[Depends(admin_required)])
def get_bug_summary(
    days: int = Query(30, description="Number of days to summarise (used if start_date/end_date not provided)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD). Overrides days param."),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD). Overrides days param."),
    include_admins: bool = Query(
        False,
        description="Include admin users in bug aggregates. Default false (exclude admins).",
    ),
    db: Session = Depends(get_db),
):
    resolved_start, resolved_end = _resolve_date_range(start_date, end_date, days)
    effective_days = (resolved_end - resolved_start).days + 1
    summary = metrics_service.get_bug_metrics(
        db=db,
        days=effective_days,
        include_admins=include_admins,
        start_date=resolved_start,
        end_date=resolved_end,
    )
    return BugMetrics(**summary)


@router.get(
    "/analytics/time-savings",
    response_model=TimeSavingsInsights,
    dependencies=[Depends(admin_required)],
)
def get_analytics_time_savings(
    days: int = Query(7, description="Number of days to summarise (used if start_date/end_date not provided)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD). Overrides days param."),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD). Overrides days param."),
    include_admins: bool = Query(
        False,
        description="Include admin users in feedback aggregates. Default false (exclude admins).",
    ),
    db: Session = Depends(get_db),
):
    resolved_start, resolved_end = _resolve_date_range(start_date, end_date, days)
    effective_days = (resolved_end - resolved_start).days + 1

    # Live query path only (OLAP/agg ready, no historical cache dependency).
    summary = metrics_service.get_time_savings_by_deliverable(
        db=db,
        days=effective_days,
        include_admins=include_admins,
        start_date=resolved_start,
        end_date=resolved_end,
    )
    return TimeSavingsInsights(**summary)


@router.get("/overview", response_model=OverviewSummary, dependencies=[Depends(admin_required)])
def get_overview(
    days: int = Query(7, description="Number of days for trends (used if start_date/end_date not provided)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD). Overrides days param."),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD). Overrides days param."),
    include_admins: bool = Query(False, description="Include admin users. Default false."),
    db: Session = Depends(get_db),
):
    """Optimized single-call endpoint for Overview dashboard.

    Returns key stats for the selected range end date, lifetime helpfulness,
    and activity trends.
    """
    resolved_start, resolved_end = _resolve_date_range(start_date, end_date, days)
    effective_days = (resolved_end - resolved_start).days + 1

    now = datetime.now(timezone.utc)
    selected_day_str = resolved_end.strftime("%Y-%m-%d")

    # Live query path only (OLAP/agg ready, no historical cache dependency).
    usage_data = usage_service.get_summary(
        db=db,
        days=effective_days,
        include_admins=include_admins,
        start_date=resolved_start,
        end_date=resolved_end,
        include_extended=False,
        include_global_totals=False,
        include_lifetime_rollups=False,
    )
    metrics_data = metrics_service.get_metrics(
        db=db,
        days=effective_days,
        include_admins=include_admins,
        start_date=resolved_start,
        end_date=resolved_end,
        include_deep_metrics=False,
    )
    time_data = metrics_service.get_time_savings_by_deliverable(
        db=db,
        days=effective_days,
        include_admins=include_admins,
        start_date=resolved_start,
        end_date=resolved_end,
    )

    # Extract today's values from per-day arrays
    active_users_per_day = usage_data.get("active_users_per_day", [])
    conversations_per_day = usage_data.get("conversations_per_day", [])
    model_cost_timeseries = usage_data.get("model_cost_timeseries", [])

    # Find today's entries
    today_users = 0
    for entry in active_users_per_day:
        if entry.get("date") == selected_day_str:
            today_users = entry.get("count", 0)
            break

    today_conversations = 0
    for entry in conversations_per_day:
        if entry.get("date") == selected_day_str:
            today_conversations = entry.get("count", 0)
            break

    today_spend = 0.0
    for entry in model_cost_timeseries:
        if entry.get("date") == selected_day_str:
            today_spend = entry.get("total", 0.0)
            break

    today_saved = 0
    today_lost = 0
    for entry in (time_data.get("time_series", []) if isinstance(time_data, dict) else []):
        if entry.get("date") == selected_day_str:
            today_saved = entry.get("saved", 0)
            today_lost = entry.get("spent", 0)
            break

    # Lifetime helpfulness from metrics
    feedback = metrics_data.get("feedback", {})
    totals = feedback.get("totals", {})
    helpful_rate = feedback.get("helpful_rate", 0.0)
    total_ratings = totals.get("total", 0)

    return OverviewSummary(
        generated_at=now.isoformat(),
        days=effective_days,
        include_admins=include_admins,
        reporting_timezone=DEFAULT_REPORTING_TIMEZONE,
        today={
            "active_users": today_users,
            "conversations": today_conversations,
            "spend_usd": today_spend,
            "time_saved_minutes": today_saved,
            "time_lost_minutes": today_lost,
        },
        lifetime={
            "helpful_rate": helpful_rate,
            "total_ratings": total_ratings,
        },
        conversations_per_day=[
            {"date": e["date"], "count": e["count"]} for e in conversations_per_day
        ],
        messages_per_day=usage_data.get("messages_per_day", []),
    )


@router.get("/analytics/tools/distribution", response_model=ToolsDistributionSummary, dependencies=[Depends(admin_required)])
def get_tools_distribution(
    days: int = Query(7, description="Number of days to summarise (used if start_date/end_date not provided). 0 for all time."),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD). Overrides days param."),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD). Overrides days param."),
    include_admins: bool = Query(
        False,
        description="Include admin users in tool distribution aggregates. Default false (exclude admins).",
    ),
    db: Session = Depends(get_db),
):
    """Get tools distribution showing which tools are most used.

    Returns counts and percentages for each tool, sorted by usage.
    """
    # Handle special case of days=0 (all time) when no explicit dates
    if days == 0 and not start_date and not end_date:
        breakdown = metrics_service.get_tools_distribution_summary(
            db=db,
            days=0,
            include_admins=include_admins,
        )
        return ToolsDistributionSummary(**breakdown)

    resolved_start, resolved_end = _resolve_date_range(start_date, end_date, days if days > 0 else 7)
    effective_days = (resolved_end - resolved_start).days + 1

    breakdown = metrics_service.get_tools_distribution_summary(
        db=db,
        days=effective_days,
        include_admins=include_admins,
        start_date=resolved_start,
        end_date=resolved_end,
    )
    return ToolsDistributionSummary(**breakdown)


@router.get(
    "/analytics/sectors",
    response_model=SectorDistributionSummary,
    dependencies=[Depends(admin_required)],
)
def get_analytics_sectors(
    days: int = Query(7, description="Number of days to summarise (used if start_date/end_date not provided)."),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD). Overrides days param."),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD). Overrides days param."),
    include_admins: bool = Query(
        False,
        description="Include admin users in distribution aggregates. Default false (exclude admins).",
    ),
    db: Session = Depends(get_db),
):
    """Get sector distribution for conversations active in the selected range."""
    resolved_start, resolved_end = _resolve_date_range(start_date, end_date, days)
    summary = build_sector_distribution(
        db=db,
        start_date=resolved_start,
        end_date=resolved_end,
        include_admins=include_admins,
    )
    return SectorDistributionSummary(**summary)


@router.get("/chat/provider", response_model=ChatProviderResponse, dependencies=[Depends(admin_required)])
def get_chat_provider(db: Session = Depends(get_db)):
    """Return effective default/power tier model configuration for admin UI."""
    provider, default_model, power_model = resolve_chat_provider(db)
    options = list(chat_model_options())
    if default_model not in options:
        options.append(default_model)
    if power_model not in options:
        options.append(power_model)
    return ChatProviderResponse(
        provider=provider,
        default_model=default_model,
        power_model=power_model,
        available_models=options,
    )


@router.put("/chat/provider", response_model=ChatProviderResponse, dependencies=[Depends(admin_required)])
def set_chat_provider(payload: ChatProviderUpdate, db: Session = Depends(get_db)):
    """Update default/power tier model settings."""
    updates: dict[str, str] = {}
    selected_default_model = payload.default_model
    selected_power_model = payload.power_model

    if selected_default_model is not None:
        try:
            normalized_default = validate_chat_model(selected_default_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            ensure_provider_is_configured(provider_for_model(normalized_default))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updates["chat_default_model"] = normalized_default

    if selected_power_model is not None:
        try:
            normalized_power = validate_chat_model(selected_power_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            ensure_provider_is_configured(provider_for_model(normalized_power))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updates["chat_power_model"] = normalized_power

    if updates:
        try:
            existing_rows = (
                db.query(AppSetting)
                .filter(AppSetting.key.in_(tuple(updates.keys())))
                .all()
            )
            existing_by_key = {row.key: row for row in existing_rows}
            for setting_key, setting_value in updates.items():
                row = existing_by_key.get(setting_key)
                if row is None:
                    db.add(AppSetting(key=setting_key, value=setting_value))
                else:
                    row.value = setting_value
            db.commit()
            invalidate_provider_cache()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to persist chat model settings") from exc

    provider, default_model, power_model = resolve_chat_provider(db)
    options = list(chat_model_options())
    if default_model not in options:
        options.append(default_model)
    if power_model not in options:
        options.append(power_model)
    return ChatProviderResponse(
        provider=provider,
        default_model=default_model,
        power_model=power_model,
        available_models=options,
    )
