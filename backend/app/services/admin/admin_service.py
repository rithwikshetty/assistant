from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_, func, case

from ...database.models import AdminUserRollup, User
from ...utils.roles import is_admin_role, non_admin_role_filter
from ..feedback_service import FeedbackService


class AdminService:
    def __init__(self) -> None:
        self._feedback_service = FeedbackService()

    def list_users(
        self,
        db: Session,
        search: Optional[str] = None,
        include_admins: bool = True,
        page: int = 1,
        page_size: int = 20,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
    ) -> Tuple[int, List[Tuple[User, int, Decimal]]]:
        """
        List users with conversation count and total cost.

        Uses per-user rollups to keep users-table sorting and pagination cheap.
        """
        query = db.query(User)
        if not include_admins:
            query = query.filter(non_admin_role_filter(User.role))

        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    User.email.ilike(like),
                    User.name.ilike(like),
                )
            )

        total = query.order_by(None).count()

        # Main query with pre-aggregated rollups.
        query = (
            query
            .outerjoin(AdminUserRollup, AdminUserRollup.user_id == User.id)
            .add_columns(func.coalesce(AdminUserRollup.conversation_count, 0).label("conversation_count"))
            .add_columns(func.coalesce(AdminUserRollup.total_cost_usd, 0).label("total_cost_usd"))
        )

        # Sorting
        is_desc = sort_dir.lower() == "desc"

        if sort_by == "conversation_count":
            sort_col = func.coalesce(AdminUserRollup.conversation_count, 0)
            query = query.order_by(sort_col.desc() if is_desc else sort_col.asc())
        elif sort_by == "total_cost_usd":
            sort_col = func.coalesce(AdminUserRollup.total_cost_usd, 0)
            query = query.order_by(sort_col.desc() if is_desc else sort_col.asc())
        else:
            # Default: sort by last_login_at (nulls last)
            nulls_last = case((User.last_login_at.is_(None), 1), else_=0)
            if is_desc:
                query = query.order_by(nulls_last.asc(), User.last_login_at.desc())
            else:
                query = query.order_by(nulls_last.desc(), User.last_login_at.asc())

        # Tiebreaker
        query = query.order_by(User.created_at.desc())

        # Pagination
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size
        results = query.offset(offset).limit(page_size).all()

        # Build result tuples: (User, conversation_count, total_cost)
        users_with_counts: List[Tuple[User, int, Decimal]] = []
        for user, conversation_count_value, total_cost_value in results:
            conversation_count = int(conversation_count_value or 0)
            total_cost = Decimal(str(total_cost_value or 0))
            users_with_counts.append((user, conversation_count, total_cost))

        return total, users_with_counts

    def _get_user_or_raise(self, db: Session, user_id: str) -> User:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
        return user

    def _count_active_admins(self, db: Session) -> int:
        """Count active admins with FOR UPDATE lock for safe mutation.

        LAT-005: Locking all active admin rows prevents two concurrent
        demote/deactivate requests from both seeing count=2 and both
        proceeding, which would leave the system with zero admins.
        """
        return len(
            db.query(User)
            .filter(
                User.role == "admin",
                User.is_active.is_(True),
            )
            .with_for_update()
            .all()
        )

    def update_user_role(
        self,
        db: Session,
        target_user_id: str,
        new_role: str,
        acting_user: User,
    ) -> User:
        normalized_role = (new_role or "").strip().lower()
        if normalized_role not in {"user", "admin"}:
            raise ValueError("Invalid role")

        user = self._get_user_or_raise(db, target_user_id)
        current_role = (user.role or "user").strip().lower()

        if str(acting_user.id) == str(user.id) and normalized_role != "admin":
            raise ValueError("You cannot demote yourself.")

        is_demoting_active_admin = (
            current_role == "admin"
            and normalized_role != "admin"
            and bool(user.is_active)
        )
        if is_demoting_active_admin and self._count_active_admins(db) <= 1:
            raise ValueError("Cannot demote the last active admin.")

        user.role = normalized_role
        if is_admin_role(current_role) != is_admin_role(normalized_role):
            self._feedback_service.adjust_non_admin_rollup_for_role_change(
                db=db,
                user_id=str(user.id),
                old_role=current_role,
                new_role=normalized_role,
            )
        db.commit()
        db.refresh(user)
        return user

    def update_user_active(
        self,
        db: Session,
        target_user_id: str,
        is_active: bool,
        acting_user: User,
    ) -> User:
        user = self._get_user_or_raise(db, target_user_id)
        next_is_active = bool(is_active)

        if str(acting_user.id) == str(user.id) and not next_is_active:
            raise ValueError("You cannot deactivate your own account.")

        is_disabling_active_admin = (
            (user.role or "").strip().lower() == "admin"
            and bool(user.is_active)
            and not next_is_active
        )
        if is_disabling_active_admin and self._count_active_admins(db) <= 1:
            raise ValueError("Cannot deactivate the last active admin.")

        user.is_active = next_is_active
        db.commit()
        db.refresh(user)
        return user


service = AdminService()
