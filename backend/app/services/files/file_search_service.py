"""File search service for content and metadata queries."""

from typing import Any, Dict, List

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ...database.models import File, FileText


class FileSearchService:
    """Handles file content and metadata search operations."""

    def search_conversation_files(
        self,
        query: str,
        conversation_id: str,
        user_id: str,
        db: Session,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search through all file content for a conversation.
        Returns list with file info and relevant excerpts.
        """
        normalized_query = (query or "").strip()
        if not normalized_query:
            return []

        like_pattern = f"%{normalized_query}%"
        candidate_limit = max(limit, 1) * 5

        matched_files = (
            db.query(File, FileText.extracted_text)
            .join(FileText, FileText.file_id == File.id)
            .filter(
                and_(
                    File.conversation_id == conversation_id,
                    File.user_id == user_id,
                    FileText.extracted_text.ilike(like_pattern),
                )
            )
            .order_by(File.updated_at.desc())
            .limit(candidate_limit)
            .all()
        )

        results: List[Dict[str, Any]] = []
        query_lower = normalized_query.lower()

        for file, extracted_text in matched_files:
            content = str(extracted_text or "")
            if not content:
                continue

            content_lower = content.lower()
            excerpts: List[str] = []
            start = 0

            while True:
                index = content_lower.find(query_lower, start)
                if index == -1:
                    break

                excerpt_start = max(0, index - 100)
                excerpt_end = min(len(content), index + len(normalized_query) + 100)
                excerpt = content[excerpt_start:excerpt_end].strip()

                if excerpt and excerpt not in excerpts:
                    excerpts.append(excerpt)

                start = index + len(query_lower)

                if len(excerpts) >= 3:
                    break

            if excerpts:
                results.append(
                    {
                        "file_id": file.id,
                        "filename": file.original_filename,
                        "file_type": file.file_type,
                        "excerpts": excerpts,
                        "match_count": len(excerpts),
                    }
                )

        results.sort(key=lambda x: x["match_count"], reverse=True)
        return results[:limit]


# Singleton instance
file_search_service = FileSearchService()
