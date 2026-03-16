from __future__ import annotations

from app.main import app


def _response_schema_ref(openapi_schema: dict, path: str, method: str, status_code: str = "200") -> str:
    response = openapi_schema["paths"][path][method]["responses"][status_code]
    content = response["content"]["application/json"]["schema"]
    return content["$ref"]


def _request_schema_ref(openapi_schema: dict, path: str, method: str) -> str:
    request_body = openapi_schema["paths"][path][method]["requestBody"]
    content = request_body["content"]["application/json"]["schema"]
    return content["$ref"]


def _property_enum_values(openapi_schema: dict, schema_name: str, property_name: str) -> list[str]:
    property_schema = openapi_schema["components"]["schemas"][schema_name]["properties"][property_name]
    if "enum" in property_schema:
        return list(property_schema["enum"])
    if "anyOf" in property_schema:
        values: list[str] = []
        for option in property_schema["anyOf"]:
            if isinstance(option, dict) and isinstance(option.get("enum"), list):
                values.extend(str(value) for value in option["enum"])
        if values:
            return values
    raise AssertionError(f"No enum values found for {schema_name}.{property_name}")


def _property_ref_names(openapi_schema: dict, schema_name: str, property_name: str) -> set[str]:
    property_schema = openapi_schema["components"]["schemas"][schema_name]["properties"][property_name]
    refs: set[str] = set()
    for key in ("oneOf", "anyOf"):
        for option in property_schema.get(key, []):
            if isinstance(option, dict) and isinstance(option.get("$ref"), str):
                refs.add(option["$ref"].split("/")[-1])
    direct_ref = property_schema.get("$ref")
    if isinstance(direct_ref, str):
        refs.add(direct_ref.split("/")[-1])
    return refs


def _property_has_untyped_object_option(openapi_schema: dict, schema_name: str, property_name: str) -> bool:
    property_schema = openapi_schema["components"]["schemas"][schema_name]["properties"][property_name]
    options = []
    for key in ("oneOf", "anyOf"):
        options.extend(option for option in property_schema.get(key, []) if isinstance(option, dict))
    if not options:
        options = [property_schema]
    for option in options:
        if option.get("$ref"):
            continue
        if option.get("type") == "object":
            return True
        if option.get("additionalProperties") is not None:
            return True
    return False


def test_explicit_response_models_are_advertised_for_hardened_json_routes() -> None:
    openapi_schema = app.openapi()

    assert _response_schema_ref(openapi_schema, "/files/{file_id}/download", "get").endswith(
        "/FileDownloadResponse"
    )
    assert _response_schema_ref(openapi_schema, "/files/{file_id}", "delete").endswith(
        "/FileDeleteResponse"
    )
    assert _response_schema_ref(openapi_schema, "/staged-files/uploads/{upload_id}/cancel", "post").endswith(
        "/StagedUploadCancelResponse"
    )
    assert _response_schema_ref(openapi_schema, "/staged-files/{staged_id}", "delete").endswith(
        "/StagedFileDeleteResponse"
    )
    assert _response_schema_ref(openapi_schema, "/projects/{project_id}/leave", "post").endswith(
        "/ProjectJoinResponse"
    )
    assert _response_schema_ref(openapi_schema, "/projects/{project_id}/transfer", "post").endswith(
        "/ProjectOwnershipTransferResponse"
    )
    assert _response_schema_ref(openapi_schema, "/auth/me", "get").endswith("/UserResponse")
    assert _response_schema_ref(openapi_schema, "/skills/manifest", "get").endswith(
        "/SkillsManifestResponse"
    )
    assert _response_schema_ref(openapi_schema, "/skills/custom", "get").endswith(
        "/CustomSkillsListResponse"
    )
    assert _response_schema_ref(openapi_schema, "/skills/custom", "post", "201").endswith(
        "/CustomSkillDetailResponse"
    )
    assert _response_schema_ref(openapi_schema, "/conversations/{conversation_id}/runs", "post").endswith(
        "/CreateRunResponse"
    )
    assert _response_schema_ref(openapi_schema, "/conversations/{conversation_id}/timeline", "get").endswith(
        "/TimelinePageResponse"
    )
    assert _response_schema_ref(openapi_schema, "/conversations/{conversation_id}/runtime", "get").endswith(
        "/ConversationRuntimeResponse"
    )
    assert _response_schema_ref(openapi_schema, "/conversations/runs/{run_id}/cancel", "post").endswith(
        "/CancelRunResponse"
    )
    assert _response_schema_ref(openapi_schema, "/conversations/runs/{run_id}/user-input", "post").endswith(
        "/SubmitRunUserInputResponse"
    )


def test_chat_contract_enums_are_advertised_in_openapi() -> None:
    openapi_schema = app.openapi()

    assert _property_enum_values(openapi_schema, "CreateRunResponse", "status") == ["queued", "running"]
    assert _property_enum_values(openapi_schema, "CancelRunResponse", "status") == [
        "queued",
        "idle",
        "running",
        "paused",
        "completed",
        "failed",
        "cancelled",
    ]
    assert _property_enum_values(openapi_schema, "ConversationRuntimeResponse", "status") == [
        "queued",
        "idle",
        "running",
        "paused",
    ]
    assert _property_enum_values(openapi_schema, "TimelineItemResponse", "type") == [
        "user_message",
        "assistant_message_partial",
        "assistant_message_final",
        "system_message",
    ]
    assert _property_enum_values(openapi_schema, "RunActivityItemResponse", "status") == [
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    queued_turn_items = openapi_schema["components"]["schemas"]["ConversationRuntimeResponse"]["properties"]["queued_turns"]["items"]
    assert queued_turn_items["$ref"].endswith("/QueuedTurnResponse")


def test_chat_payload_schemas_are_explicit_in_openapi() -> None:
    openapi_schema = app.openapi()

    run_activity_payload_ref = openapi_schema["components"]["schemas"]["RunActivityItemResponse"]["properties"]["payload"]["$ref"]
    assert run_activity_payload_ref.endswith("/RunActivityPayloadResponse")

    timeline_payload_ref = openapi_schema["components"]["schemas"]["TimelineItemResponse"]["properties"]["payload"]["$ref"]
    assert timeline_payload_ref.endswith("/TimelineMessagePayloadResponse")

    runtime_usage_ref = openapi_schema["components"]["schemas"]["ConversationRuntimeResponse"]["properties"]["usage"]["$ref"]
    assert runtime_usage_ref.endswith("/RunUsagePayloadResponse")

    attachments_property = openapi_schema["components"]["schemas"]["TimelineMessagePayloadResponse"]["properties"]["attachments"]
    attachments_items = None
    if "items" in attachments_property:
        attachments_items = attachments_property["items"]
    else:
        for option in attachments_property.get("anyOf", []):
            if isinstance(option, dict) and "items" in option:
                attachments_items = option["items"]
                break
    assert attachments_items is not None
    assert attachments_items["$ref"].endswith("/TimelineAttachmentResponse")

    request_refs = _property_ref_names(openapi_schema, "RunActivityPayloadResponse", "request")
    assert request_refs == {"RequestUserInputRequestPayload"}

    arguments_refs = _property_ref_names(openapi_schema, "RunActivityPayloadResponse", "arguments")
    assert {
        "QueryToolArgumentsResponse",
        "RetrievalProjectFilesToolArgumentsResponse",
        "FileReadToolArgumentsResponse",
        "TasksToolArgumentsResponse",
        "LoadSkillToolArgumentsResponse",
        "ChartToolArgumentsResponse",
        "GanttToolArgumentsResponse",
        "RequestUserInputToolArgumentsResponse",
        "ExecuteCodeToolArgumentsResponse",
    }.issubset(arguments_refs)
    assert not _property_has_untyped_object_option(openapi_schema, "RunActivityPayloadResponse", "arguments")

    result_refs = _property_ref_names(openapi_schema, "RunActivityPayloadResponse", "result")
    assert {
        "RequestUserInputPendingResultPayload",
        "RequestUserInputCompletedResultPayload",
        "ChartToolResultPayloadResponse",
        "GanttToolResultPayloadResponse",
        "WebSearchResultPayloadResponse",
        "KnowledgeResultPayloadResponse",
        "CalculationResultPayloadResponse",
        "TasksResultPayloadResponse",
        "FileReadResultPayloadResponse",
        "ExecuteCodeResultPayloadResponse",
        "SkillResultPayloadResponse",
    }.issubset(result_refs)
    assert not _property_has_untyped_object_option(openapi_schema, "RunActivityPayloadResponse", "result")

    error_refs = _property_ref_names(openapi_schema, "RunActivityPayloadResponse", "error")
    assert "ToolErrorPayloadResponse" in error_refs
    assert not _property_has_untyped_object_option(openapi_schema, "RunActivityPayloadResponse", "error")

    assert not _property_has_untyped_object_option(openapi_schema, "RunActivityPayloadResponse", "request")


def test_interactive_input_request_schemas_are_explicit_in_openapi() -> None:
    openapi_schema = app.openapi()

    assert _request_schema_ref(openapi_schema, "/conversations/runs/{run_id}/user-input", "post").endswith(
        "/SubmitRunUserInputRequest"
    )

    pending_requests_property = openapi_schema["components"]["schemas"]["ConversationRuntimeResponse"]["properties"]["pending_requests"]
    pending_request_union = pending_requests_property["items"]
    assert pending_request_union["discriminator"]["propertyName"] == "tool_name"
    pending_request_refs = {
        option["$ref"].split("/")[-1]
        for option in pending_request_union["oneOf"]
    }
    assert pending_request_refs == {"RequestUserInputPendingRequestResponse"}


def test_non_json_routes_are_documented_with_explicit_content_types() -> None:
    openapi_schema = app.openapi()

    stream_response = openapi_schema["paths"]["/projects/{project_id}/knowledge-base/processing-status/stream"]["get"]["responses"]["200"]
    assert "text/event-stream" in stream_response["content"]

    custom_download_response = openapi_schema["paths"]["/skills/custom/{skill_id}/files/{file_path}"]["get"]["responses"]["200"]
    assert "application/octet-stream" in custom_download_response["content"]

    global_download_response = openapi_schema["paths"]["/skills/{skill_id}/files/{file_path}"]["get"]["responses"]["200"]
    assert "application/octet-stream" in global_download_response["content"]
