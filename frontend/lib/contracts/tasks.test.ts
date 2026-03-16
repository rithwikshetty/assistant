import { describe, expect, it } from "vitest";

import {
  parseTask,
  parseTaskCommentsResponse,
  parseTaskPriority,
  parseTaskStatus,
  parseTaskUnseenCount,
} from "./tasks";

describe("task contracts", () => {
  it("parses canonical task payloads", () => {
    expect(
      parseTask({
        id: "task_1",
        created_by_id: "user_1",
        created_by_name: "User One",
        created_by_email: "user@example.com",
        category: "Delivery",
        conversation_id: null,
        title: "Ship deployment checklist",
        description: null,
        status: "in_progress",
        priority: "high",
        due_at: "2026-03-20",
        completed_at: null,
        is_archived: false,
        archived_at: null,
        created_at: "2026-03-12T00:00:00Z",
        updated_at: "2026-03-12T01:00:00Z",
        assignees: [],
        is_assigned_to_me: true,
        is_unseen_for_me: false,
      }),
    ).toMatchObject({
      id: "task_1",
      status: "in_progress",
      priority: "high",
    });
  });

  it("rejects invalid task status and priority values", () => {
    expect(() => parseTaskStatus("completed")).toThrow(/task\.status/);
    expect(() => parseTaskPriority("critical")).toThrow(/task\.priority/);
  });

  it("parses comment envelopes explicitly", () => {
    expect(
      parseTaskCommentsResponse({
        items: [
          {
            id: "comment_1",
            task_id: "task_1",
            user_id: "user_1",
            user_name: "User One",
            user_email: "user@example.com",
            content: "Looks good",
            created_at: "2026-03-12T00:00:00Z",
            updated_at: "2026-03-12T00:00:00Z",
          },
        ],
      }),
    ).toHaveLength(1);
  });

  it("parses unseen count payloads strictly", () => {
    expect(parseTaskUnseenCount({ count: 3 })).toBe(3);
    expect(() => parseTaskUnseenCount({ count: "3" })).toThrow(/must be numeric/);
  });
});
