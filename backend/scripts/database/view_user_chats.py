#!/usr/bin/env python3
"""
Inspect all conversations and visible chat messages for a specific user.
Usage: python view_user_chats.py <email>
"""

import os
import sys

from sqlalchemy.orm import Session

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from app.config.database import sync_engine
from app.database.models import Conversation, Message, User

VISIBLE_ROLES = ("user", "assistant")


def _extract_preview(text: object) -> str:
    if not isinstance(text, str):
        return ""
    normalized = " ".join(text.strip().split())
    if not normalized:
        return ""
    return normalized[:100] + "..." if len(normalized) > 100 else normalized


def view_user_chats(username: str) -> bool:
    """View all conversations and visible messages for a user by email."""
    with Session(sync_engine) as db:
        user = db.query(User).filter(User.email == username).first()
        if not user:
            print(f"User '{username}' not found")
            return False

        print(f"User: {user.email} (ID: {user.id})")
        if user.created_at:
            print(f"Created: {user.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        conversations = (
            db.query(Conversation)
            .filter(Conversation.user_id == user.id)
            .order_by(Conversation.created_at.desc())
            .all()
        )
        if not conversations:
            print("No conversations found for this user")
            return True

        print(f"Found {len(conversations)} conversation(s):")
        print("=" * 80)

        for i, conv in enumerate(conversations, 1):
            messages = (
                db.query(Message)
                .filter(
                    Message.conversation_id == conv.id,
                    Message.role.in_(VISIBLE_ROLES),
                )
                .order_by(Message.created_at.asc(), Message.id.asc())
                .all()
            )

            completed_turn_count = sum(
                1
                for message in messages
                if message.role in {"user", "assistant"}
                and str(message.status or "").strip().lower() in {
                    "completed",
                    "failed",
                    "cancelled",
                    "awaiting_input",
                }
            )

            print(f"\n{i}. {conv.title}")
            print(f"   ID: {conv.id}")
            if conv.created_at:
                print(f"   Created: {conv.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if conv.updated_at:
                print(f"   Updated: {conv.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Visible messages: {len(messages)}")
            print(f"   Completed turns: {completed_turn_count}")

            if messages:
                print("   Message history:")
                for j, message in enumerate(messages, 1):
                    preview = _extract_preview(message.text) or "[no text]"
                    status = str(message.status or "").strip().lower()
                    suffix = f" ({status})" if status and status != "completed" else ""
                    timestamp = message.created_at.strftime("%H:%M:%S") if message.created_at else "N/A"
                    print(f"      {j}. [{timestamp}] {message.role}{suffix}: {preview}")

            if i < len(conversations):
                print("-" * 80)

        total_visible_messages = (
            db.query(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(
                Conversation.user_id == user.id,
                Message.role.in_(VISIBLE_ROLES),
            )
            .count()
        )
        print("\n" + "=" * 80)
        print(f"Summary: {len(conversations)} conversations, {total_visible_messages} visible messages")
        return True


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python view_user_chats.py <email>")
        print("Example: python view_user_chats.py john.doe@company.com")
        sys.exit(1)

    username = sys.argv[1]
    success = view_user_chats(username)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
