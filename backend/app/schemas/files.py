from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Literal, Optional, List, Dict, Any

class FileUploadResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    created_at: datetime
    redaction_requested: bool = False
    redaction_applied: bool = False
    redacted_categories: List[str] = Field(default_factory=list)
    user_redaction_applied: bool = False
    user_redaction_hits: List[str] = Field(default_factory=list)
    extracted_text: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class FileInfo(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    blob_url: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class FileQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="Search query for file content")
    conversation_id: str = Field(..., description="Conversation ID (UUID) to search files in")

class FileQueryResponse(BaseModel):
    files_found: int
    results: List[dict]  # Will contain filename, excerpts, relevance scores
    
class ConversationFilesResponse(BaseModel):
    total_files: int
    total_size: int  # Total size in bytes
    files: List[FileInfo]


class FileContentChunkResponse(BaseModel):
    file_id: str
    filename: str
    original_filename: str
    file_type: str
    content: str
    chunk_start: int = Field(..., ge=0)
    chunk_end: int = Field(..., ge=0)
    total_length: int = Field(..., ge=0)
    has_more: bool
    is_truncated: bool
    encoding: str = "utf-8"
    metadata: Optional[Dict[str, Any]] = None
    checksum: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FileDownloadResponse(BaseModel):
    download_url: str
    filename: str
    file_type: str
    expires_in_days: int
    expires_in_minutes: int


class FileDeleteResponse(BaseModel):
    message: str


class ProjectKnowledgeUploader(BaseModel):
    id: str
    name: Optional[str]
    email: Optional[str]


class ProjectKnowledgeFile(BaseModel):
    id: str
    project_id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    created_at: datetime
    updated_at: datetime
    uploaded_by: ProjectKnowledgeUploader
    processing_status: str = "completed"  # pending, processing, completed, failed
    indexed_chunk_count: int = 0
    indexed_at: Optional[datetime] = None
    processing_error: Optional[str] = None


class ProjectKnowledgeFilesPageResponse(BaseModel):
    project_id: str
    files: List[ProjectKnowledgeFile]
    limit: int
    offset: int
    has_more: bool
    next_offset: Optional[int] = None


class ProjectKnowledgeProcessingStatus(BaseModel):
    """Status of file processing for a project's knowledge base."""
    project_id: str
    total: int
    pending: int
    processing: int
    completed: int
    failed: int
    all_completed: bool


class ProjectKnowledgeSummaryResponse(BaseModel):
    project_id: str
    total_files: int
    total_size: int
    file_types: Dict[str, int]
    pending: int
    processing: int
    completed: int
    failed: int
    all_completed: bool


class ProjectKnowledgeSummaryItem(BaseModel):
    file_id: str
    original_filename: str
    file_type: str
    file_size: int
    created_at: datetime

class ProjectKnowledgeContextResponse(BaseModel):
    project_id: str
    total_files: int
    total_size: int
    files: List[ProjectKnowledgeSummaryItem]


class StagedFileResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    created_at: datetime
    processing_status: str = "pending"
    processing_error: Optional[str] = None
    redaction_requested: bool = False
    redaction_applied: bool = False
    redacted_categories: List[str] = Field(default_factory=list)
    extracted_text: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class StagedUploadCancelResponse(BaseModel):
    status: Literal["cancelled"]
    staged_files_removed: int


class StagedFileDeleteResponse(BaseModel):
    message: str


class ProjectKnowledgeArchiveJobResponse(BaseModel):
    job_id: str
    project_id: str
    status: str
    total_files: int = 0
    included_files: int = 0
    skipped_files: int = 0
    archive_filename: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ProjectKnowledgeBulkDeleteResponse(BaseModel):
    message: str
    deleted: int


class ProjectKnowledgeDeleteResponse(BaseModel):
    message: str
