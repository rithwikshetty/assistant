import { describe, expect, it } from "vitest";

import {
  parseConversationRuntimeResponse,
  parseCreateRunResponse,
  parseConversationResponsePayload,
  parseStreamEvent,
} from "./chat";

describe("chat transport contracts", () => {
  it("parses create-run responses without stream_url", () => {
    expect(
      parseCreateRunResponse({
        run_id: "run_1",
        user_message_id: "msg_1",
        status: "running",
      }),
    ).toEqual({
      run_id: "run_1",
      user_message_id: "msg_1",
      status: "running",
      queue_position: 0,
    });
  });

  it("rejects invalid run and timeline status values", () => {
    expect(() =>
      parseCreateRunResponse({
        run_id: "run_1",
        user_message_id: "msg_1",
        status: "streaming",
      }),
    ).toThrow("createRun.status must be one of");

    expect(() =>
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "completed",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [],
      }),
    ).toThrow("conversationRuntime.status must be one of");
  });

  it("parses conversation payloads with the compact transport shape", () => {
    expect(
      parseConversationResponsePayload({
        id: "conv_1",
        title: "New chat",
        created_at: "2026-03-09T00:00:00Z",
        updated_at: "2026-03-09T00:00:00Z",
        last_message_at: "2026-03-09T00:00:00Z",
        message_count: 0,
        owner_id: "user_1",
        is_owner: true,
        can_edit: true,
      }),
    ).toEqual({
      id: "conv_1",
      title: "New chat",
      created_at: "2026-03-09T00:00:00Z",
      updated_at: "2026-03-09T00:00:00Z",
      last_message_at: "2026-03-09T00:00:00Z",
      message_count: 0,
      last_message_preview: undefined,
      project_id: undefined,
      parent_conversation_id: undefined,
      branch_from_message_id: undefined,
      archived: false,
      archived_at: undefined,
      archived_by: undefined,
      is_pinned: false,
      pinned_at: undefined,
      owner_id: "user_1",
      owner_name: undefined,
      owner_email: undefined,
      is_owner: true,
      can_edit: true,
      requires_feedback: false,
      awaiting_user_input: false,
      context_usage: null,
    });
  });

  it("parses runtime usage through the canonical run-usage contract", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        resume_since_stream_event_id: 4,
        activity_cursor: 4,
        pending_requests: [],
        activity_items: [],
        usage: {
          input_tokens: "180",
          cache_creation_input_tokens: 12,
          aggregated_total_tokens: 420.8,
        },
      }).usage,
    ).toEqual({
      input_tokens: 180,
      cache_creation_input_tokens: 12,
      aggregated_total_tokens: 421,
    });
  });

  it("drops malformed stream events and keeps canonical valid payloads", () => {
    expect(parseStreamEvent(null)).toBeNull();
    expect(parseStreamEvent({ id: 1 })).toBeNull();
    expect(
      parseStreamEvent({
        id: "6",
        type: "response.created",
        data: { response_id: "resp_1" },
      }),
    ).toBeNull();
    expect(
      parseStreamEvent({
        id: "7",
        type: "done",
        data: { status: "completed" },
      }),
    ).toEqual({
      id: 7,
      type: "done",
      data: {
        conversationId: null,
        runId: null,
        runMessageId: null,
        assistantMessageId: null,
        status: "completed",
        cancelled: false,
        pendingRequests: [],
        usage: null,
        conversationUsage: null,
        elapsedSeconds: null,
        costUsd: null,
      },
    });
  });

  it("parses stream usage payloads through shared usage contracts", () => {
    expect(
      parseStreamEvent({
        id: 8,
        type: "conversation_usage",
        data: {
          source: "stream",
          usage: {
            input_tokens: "45",
            aggregated_total_tokens: 90,
          },
          conversationUsage: {
            current_context_tokens: "300",
            max_context_tokens: 128000,
          },
        },
      }),
    ).toEqual({
      id: 8,
      type: "conversation_usage",
      data: {
        source: "stream",
        usage: {
          input_tokens: 45,
          aggregated_total_tokens: 90,
        },
        conversationUsage: {
          current_context_tokens: 300,
          max_context_tokens: 128000,
        },
      },
    });
  });

  it("normalizes runtime update payloads into canonical shapes", () => {
    expect(
      parseStreamEvent({
        id: 8,
        type: "runtime_update",
        data: { statusLabel: "Searching sources" },
      }),
    ).toEqual({
      id: 8,
      type: "runtime_update",
      data: { statusLabel: "Searching sources" },
    });

    expect(
      parseStreamEvent({
        id: 9,
        type: "runtime_update",
        data: {
          statusLabel: "Generating response",
        },
      }),
    ).toEqual({
      id: 9,
      type: "runtime_update",
      data: { statusLabel: "Generating response" },
    });
  });

  it("preserves whitespace in streamed content deltas", () => {
    expect(
      parseStreamEvent({
        id: 10,
        type: "content.delta",
        data: {
          delta: " workflow first, then benchmark",
          statusLabel: "Generating response",
        },
      }),
    ).toEqual({
      id: 10,
      type: "content.delta",
      data: {
        delta: " workflow first, then benchmark",
        statusLabel: "Generating response",
      },
    });

    expect(
      parseStreamEvent({
        id: 11,
        type: "content.delta",
        data: {
          delta: " ",
        },
      }),
    ).toEqual({
      id: 11,
      type: "content.delta",
      data: {
        delta: " ",
        statusLabel: null,
      },
    });
  });

  it("parses tool ordering metadata for live interleaving", () => {
    expect(
      parseStreamEvent({
        id: 12,
        type: "tool.started",
        data: {
          toolCallId: "call_1",
          toolName: "retrieval_web_search",
          arguments: { query: "hvac benchmark" },
          position: 42,
          sequence: 3,
          statusLabel: "Using web search",
        },
      }),
    ).toEqual({
      id: 12,
      type: "tool.started",
      data: {
        toolCallId: "call_1",
        toolName: "retrieval_web_search",
        arguments: { query: "hvac benchmark" },
        position: 42,
        sequence: 3,
        statusLabel: "Using web search",
      },
    });
  });

  it("parses tool.completed websocket payloads through visible-tool contracts", () => {
    expect(
      parseStreamEvent({
        id: 15,
        type: "tool.completed",
        data: {
          toolCallId: "chart_1",
          toolName: "viz_create_chart",
          result: {
            type: "bar",
            title: "Uplift",
            data: [{ label: "Baseline", uplift: 12.5 }],
          },
          position: 42,
          sequence: 4,
        },
      }),
    ).toEqual({
      id: 15,
      type: "tool.completed",
      data: {
        toolCallId: "chart_1",
        toolName: "viz_create_chart",
        result: {
          type: "bar",
          title: "Uplift",
          data: [{ label: "Baseline", uplift: 12.5 }],
          config: null,
          auto_retry: null,
        },
        position: 42,
        sequence: 4,
      },
    });
  });

  it("preserves supported tool.started events even when argument parsing falls back to a raw record", () => {
    const event = parseStreamEvent({
      id: 44,
      type: "tool.started",
      data: {
        toolCallId: "call_doc",
        toolName: "retrieval_web_search",
        arguments: {
          query: "hvac benchmark",
          unexpected_flag: true,
        },
        statusLabel: "Searching documents",
        position: 12,
        sequence: 4,
      },
    });

    expect(event).toEqual({
      id: 44,
      type: "tool.started",
      data: {
        toolCallId: "call_doc",
        toolName: "retrieval_web_search",
        arguments: {
          query: "hvac benchmark",
        },
        statusLabel: "Searching documents",
        position: 12,
        sequence: 4,
      },
    });
  });

  it("falls back to the raw argument record for supported tools with untyped argument shapes", () => {
    const event = parseStreamEvent({
      id: 45,
      type: "tool.started",
      data: {
        toolCallId: "call_calc",
        toolName: "calc_unit_rate",
        arguments: {
          total_cost: "1000",
          quantity: "25",
          unit: "m2",
        },
        statusLabel: "Calculating unit rate",
        position: 18,
        sequence: 5,
      },
    });

    expect(event).toEqual({
      id: 45,
      type: "tool.started",
      data: {
        toolCallId: "call_calc",
        toolName: "calc_unit_rate",
        arguments: {
          total_cost: "1000",
          quantity: "25",
          unit: "m2",
        },
        statusLabel: "Calculating unit rate",
        position: 18,
        sequence: 5,
      },
    });
  });

  it("parses tool.failed websocket payloads through the canonical error contract", () => {
    expect(
      parseStreamEvent({
        id: 16,
        type: "tool.failed",
        data: {
          toolCallId: "call_2",
          toolName: "execute_code",
          error: {
            message: "syntax error at or near SELECT",
            code: "QUERY_FAILED",
          },
          position: 8,
          sequence: 5,
        },
      }),
    ).toEqual({
      id: 16,
      type: "tool.failed",
      data: {
        toolCallId: "call_2",
        toolName: "execute_code",
        error: {
          message: "syntax error at or near SELECT",
          code: "QUERY_FAILED",
        },
        position: 8,
        sequence: 5,
      },
    });
  });

  it("rejects legacy snake_case websocket payload aliases", () => {
    expect(
      parseStreamEvent({
        id: 13,
        type: "runtime_update",
        data: { current_step: "Searching sources" },
      }),
    ).toEqual({
      id: 13,
      type: "runtime_update",
      data: { statusLabel: null },
    });

    expect(
      parseStreamEvent({
        id: 14,
        type: "tool.started",
        data: {
          tool_call_id: "call_1",
          tool_name: "web_search",
          status_label: "Using web search",
        },
      }),
    ).toBeNull();
  });

  it("drops malformed tool websocket payloads instead of throwing", () => {
    expect(
      parseStreamEvent({
        id: 17,
        type: "tool.started",
        data: {
          toolCallId: "call_1",
          statusLabel: "Using tool",
        },
      }),
    ).toBeNull();

    expect(
      parseStreamEvent({
        id: 18,
        type: "tool.completed",
        data: {
          toolCallId: "call_2",
          toolName: "unknown_tool",
          result: {},
        },
      }),
    ).toBeNull();
  });

  it("parses runtime payloads with a canonical live assistant message", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        run_id: "run_1",
        run_message_id: "msg_1",
        assistant_message_id: "assist_1",
        status_label: "Analysing project data",
        draft_text: "Working draft",
        resume_since_stream_event_id: 9,
        activity_cursor: 2,
        pending_requests: [],
        activity_items: [],
        live_message: {
          id: "assist_1",
          seq: 10,
          run_id: "run_1",
          type: "assistant_message_partial",
          actor: "assistant",
          created_at: "2026-03-11T00:00:00Z",
          role: "assistant",
          text: "Working draft",
          activity_items: [],
          payload: {
            text: "Working draft",
            status: "running",
          },
        },
      }),
    ).toMatchObject({
      conversation_id: "conv_1",
      status: "running",
      resume_since_stream_event_id: 9,
      activity_cursor: 2,
      live_message: {
        id: "assist_1",
        seq: 10,
        run_id: "run_1",
        type: "assistant_message_partial",
        actor: "assistant",
        created_at: "2026-03-11T00:00:00Z",
        role: "assistant",
        text: "Working draft",
        activity_items: [],
        payload: {
          text: "Working draft",
          status: "running",
        },
      },
    });
  });

  it("drops unsupported run-activity tool payload details without crashing runtime parsing", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        resume_since_stream_event_id: 1,
        activity_cursor: 1,
        pending_requests: [],
        activity_items: [
          {
            id: "activity_1",
            run_id: "run_1",
            item_key: "tool:call_1",
            kind: "tool",
            status: "running",
            title: "Unknown Tool",
            summary: null,
            sequence: 1,
            payload: {
              tool_call_id: "call_1",
              tool_name: "unknown_tool",
              arguments: { foo: "bar" },
              result: { baz: "qux" },
            },
            created_at: "2026-03-13T00:00:00Z",
            updated_at: "2026-03-13T00:00:00Z",
          },
        ],
      }).activity_items[0]?.payload,
    ).toMatchObject({
      tool_call_id: "call_1",
      tool_name: "unknown_tool",
      arguments: undefined,
      result: undefined,
    });
  });

  it("parses queued runtime turns with explicit fields", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: false,
        status: "queued",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [],
        queued_turns: [
          {
            queue_position: 1,
            run_id: "run_queued",
            user_message_id: "msg_queued",
            blocked_by_run_id: "run_active",
            created_at: "2026-03-12T00:00:00Z",
          },
        ],
      }),
    ).toMatchObject({
      queued_turns: [
        {
          queue_position: 1,
          run_id: "run_queued",
          user_message_id: "msg_queued",
          blocked_by_run_id: "run_active",
          created_at: "2026-03-12T00:00:00Z",
        },
      ],
    });
  });

  it("parses canonical timeline payload fields without alias fallbacks", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [
          {
            id: "activity_1",
            run_id: "run_1",
            item_key: "tool:call_1",
            kind: "tool",
            status: "completed",
            sequence: 1,
            payload: {
              tool_call_id: "call_1",
              tool_name: "retrieval_web_search",
              position: 2,
              result: {
                content: "Found relevant sources",
                citations: [],
              },
            },
            created_at: "2026-03-12T00:00:00Z",
            updated_at: "2026-03-12T00:00:01Z",
          },
        ],
        live_message: {
          id: "assist_1",
          seq: 1,
          run_id: "run_1",
          type: "assistant_message_final",
          actor: "assistant",
          created_at: "2026-03-12T00:00:00Z",
          role: "assistant",
          text: "Answer",
          payload: {
            text: "Answer",
            status: "completed",
            response_latency_ms: 321,
            finish_reason: "stop",
          },
        },
      }),
    ).toMatchObject({
      activity_items: [
        {
          payload: {
            tool_call_id: "call_1",
            tool_name: "retrieval_web_search",
            position: 2,
            result: {
              content: "Found relevant sources",
              citations: [],
            },
          },
        },
      ],
      live_message: {
        payload: {
          text: "Answer",
          status: "completed",
          response_latency_ms: 321,
          finish_reason: "stop",
        },
      },
    });
  });

  it("parses run-activity arguments through canonical tool-argument contracts", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [
          {
            id: "activity_1",
            run_id: "run_1",
            item_key: "tool:call_1",
            kind: "tool",
            status: "running",
            sequence: 1,
            payload: {
              tool_call_id: "call_1",
              tool_name: "load_skill",
              arguments: {
                skill_id: "cost-estimation",
              },
            },
            created_at: "2026-03-12T00:00:00Z",
            updated_at: "2026-03-12T00:00:01Z",
          },
        ],
      }),
    ).toMatchObject({
      activity_items: [
        {
          payload: {
            tool_call_id: "call_1",
            tool_name: "load_skill",
            arguments: {
              skill_id: "cost-estimation",
            },
          },
        },
      ],
    });
  });

  it("parses interactive run-activity request/result payloads explicitly", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "paused",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [
          {
            id: "activity_1",
            run_id: "run_1",
            item_key: "user_input:call_1",
            kind: "user_input",
            status: "completed",
            sequence: 1,
            payload: {
              tool_call_id: "call_1",
              tool_name: "request_user_input",
              request: {
                tool: "request_user_input",
                title: "Need context",
                prompt: "Pick one",
                questions: [
                  {
                    id: "q1",
                    question: "Priority?",
                    options: [
                      { label: "Fast", description: "Move quickly with a lean answer" },
                      { label: "Deep", description: "Spend longer for a fuller analysis" },
                    ],
                  },
                ],
              },
              result: {
                status: "completed",
                interaction_type: "user_input",
                request: {
                  tool: "request_user_input",
                  title: "Need context",
                  prompt: "Pick one",
                  questions: [
                    {
                      id: "q1",
                      question: "Priority?",
                      options: [
                        { label: "Fast", description: "Move quickly with a lean answer" },
                        { label: "Deep", description: "Spend longer for a fuller analysis" },
                      ],
                    },
                  ],
                },
                answers: [{ question_id: "q1", option_label: "Fast" }],
                custom_response: "Keep it concise.",
              },
            },
            created_at: "2026-03-13T00:00:00Z",
            updated_at: "2026-03-13T00:00:01Z",
          },
        ],
      }),
    ).toMatchObject({
      activity_items: [
        {
          payload: {
            request: {
              tool: "request_user_input",
              title: "Need context",
            },
            result: {
              status: "completed",
              interaction_type: "user_input",
              answers: [{ question_id: "q1", option_label: "Fast" }],
              custom_response: "Keep it concise.",
            },
          },
        },
      ],
    });
  });

  it("parses visible-tool run-activity results through canonical payload contracts", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [
          {
            id: "activity_chart",
            run_id: "run_1",
            item_key: "tool:chart_1",
            kind: "tool",
            status: "completed",
            sequence: 1,
            payload: {
              tool_call_id: "chart_1",
              tool_name: "viz_create_chart",
              result: {
                type: "bar",
                title: "Segment uplift",
                data: [
                  { segment: "Baseline", uplift: 12.5 },
                  { segment: "Stretch", uplift: 9.0 },
                ],
                config: {
                  x_axis_key: "segment",
                  data_keys: ["uplift"],
                },
              },
            },
            created_at: "2026-03-13T00:00:00Z",
            updated_at: "2026-03-13T00:00:01Z",
          },
          {
            id: "activity_gantt",
            run_id: "run_1",
            item_key: "tool:gantt_1",
            kind: "tool",
            status: "completed",
            sequence: 2,
            payload: {
              tool_call_id: "gantt_1",
              tool_name: "viz_create_gantt",
              result: {
                title: "Tender programme",
                tasks: [
                  {
                    id: "task_1",
                    name: "Scope review",
                    start: "2026-03-01",
                    end: "2026-03-05",
                  },
                ],
                view_mode: "Week",
              },
            },
            created_at: "2026-03-13T00:00:02Z",
            updated_at: "2026-03-13T00:00:03Z",
          },
        ],
      }),
    ).toMatchObject({
      activity_items: [
        {
          payload: {
            result: {
              type: "bar",
              title: "Segment uplift",
              config: {
                x_axis_key: "segment",
                data_keys: ["uplift"],
              },
            },
          },
        },
        {
          payload: {
            result: {
              title: "Tender programme",
              view_mode: "Week",
            },
          },
        },
      ],
    });
  });

  it("parses grouped tool results through canonical payload contracts", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [
          {
            id: "activity_web",
            run_id: "run_1",
            item_key: "tool:web_1",
            kind: "tool",
            status: "completed",
            sequence: 1,
            payload: {
              tool_call_id: "web_1",
              tool_name: "retrieval_web_search",
              result: {
                content: "Summary",
                citations: [
                  {
                    index: 1,
                    url: "https://example.com/article",
                    title: "Example",
                  },
                ],
              },
            },
            created_at: "2026-03-13T00:00:00Z",
            updated_at: "2026-03-13T00:00:01Z",
          },
          {
            id: "activity_calc",
            run_id: "run_1",
            item_key: "tool:calc_1",
            kind: "tool",
            status: "completed",
            sequence: 2,
            payload: {
              tool_call_id: "calc_1",
              tool_name: "calc_contingency",
              result: {
                operation: "calc_contingency",
                operation_label: "Contingency",
                result: {
                  display: "£110,000.00",
                  value: 110000,
                },
              },
            },
            created_at: "2026-03-13T00:00:02Z",
            updated_at: "2026-03-13T00:00:03Z",
          },
          {
            id: "activity_tasks",
            run_id: "run_1",
            item_key: "tool:tasks_1",
            kind: "tool",
            status: "completed",
            sequence: 3,
            payload: {
              tool_call_id: "tasks_1",
              tool_name: "tasks",
              result: {
                action: "create",
                task: {
                  id: "task_1",
                  title: "Review estimate",
                },
              },
            },
            created_at: "2026-03-13T00:00:04Z",
            updated_at: "2026-03-13T00:00:05Z",
          },
        ],
      }),
    ).toMatchObject({
      activity_items: [
        {
          payload: {
            result: {
              content: "Summary",
              citations: [{ url: "https://example.com/article" }],
            },
          },
        },
        {
          payload: {
            result: {
              operation: "calc_contingency",
              result: { display: "£110,000.00" },
            },
          },
        },
        {
          payload: {
            result: {
              action: "create",
              task: { id: "task_1", title: "Review estimate" },
            },
          },
        },
      ],
    });
  });

  it("parses specialized tool results through canonical payload contracts", () => {
    expect(
      parseConversationRuntimeResponse({
        conversation_id: "conv_1",
        active: true,
        status: "running",
        resume_since_stream_event_id: 0,
        activity_cursor: 0,
        pending_requests: [],
        activity_items: [
          {
            id: "activity_file",
            run_id: "run_1",
            item_key: "tool:file_1",
            kind: "tool",
            status: "completed",
            sequence: 1,
            payload: {
              tool_call_id: "file_1",
              tool_name: "file_read",
              result: {
                file_id: "file_1",
                filename: "report.pdf",
                chunks: [{ content: "Executive summary" }],
              },
            },
            created_at: "2026-03-13T00:00:00Z",
            updated_at: "2026-03-13T00:00:01Z",
          },
          {
            id: "activity_exec",
            run_id: "run_1",
            item_key: "tool:exec_1",
            kind: "tool",
            status: "completed",
            sequence: 2,
            payload: {
              tool_call_id: "exec_1",
              tool_name: "execute_code",
              result: {
                success: true,
                execution_time_ms: 420,
                generated_files: [{ file_id: "file_2", filename: "output.csv" }],
              },
            },
            created_at: "2026-03-13T00:00:02Z",
            updated_at: "2026-03-13T00:00:03Z",
          },
          {
            id: "activity_skill",
            run_id: "run_1",
            item_key: "tool:skill_1",
            kind: "tool",
            status: "completed",
            sequence: 3,
            payload: {
              tool_call_id: "skill_1",
              tool_name: "load_skill",
              result: {
                skill_id: "cost-estimation",
                name: "Cost Estimation",
                content: "# Cost Estimation",
              },
            },
            created_at: "2026-03-13T00:00:04Z",
            updated_at: "2026-03-13T00:00:05Z",
          },
        ],
      }),
    ).toMatchObject({
      activity_items: [
        {
          payload: {
            result: {
              file_id: "file_1",
              chunks: [{ content: "Executive summary" }],
            },
          },
        },
        {
          payload: {
            result: {
              success: true,
              execution_time_ms: 420,
              generated_files: [{ file_id: "file_2" }],
            },
          },
        },
        {
          payload: {
            result: {
              skill_id: "cost-estimation",
              name: "Cost Estimation",
            },
          },
        },
      ],
    });
  });
});
