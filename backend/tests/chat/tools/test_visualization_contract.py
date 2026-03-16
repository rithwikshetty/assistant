from app.chat.tools.visualization import execute_create_chart, execute_create_gantt


def test_execute_create_chart_returns_canonical_payload() -> None:
    result = execute_create_chart(
        {
            "type": "bar",
            "title": "Segment uplift",
            "data": [
                {"segment": "Baseline", "uplift": 12.5},
                {"segment": "Stretch", "uplift": 9.0},
            ],
            "x_axis_key": "segment",
            "data_keys": ["uplift"],
            "x_axis_label": "Segment",
            "y_axis_label": "Uplift (%)",
            "colors": ["#001366"],
        }
    )

    assert result == {
        "type": "bar",
        "title": "Segment uplift",
        "data": [
            {"segment": "Baseline", "uplift": 12.5},
            {"segment": "Stretch", "uplift": 9.0},
        ],
        "config": {
            "x_axis_key": "segment",
            "data_keys": ["uplift"],
            "x_axis_label": "Segment",
            "y_axis_label": "Uplift (%)",
            "colors": ["#001366"],
        },
    }


def test_execute_create_gantt_returns_canonical_payload() -> None:
    result = execute_create_gantt(
        {
            "title": "Tender programme",
            "tasks": [
                {
                    "id": "task_1",
                    "name": "Scope review",
                    "start": "2026-03-01",
                    "end": "2026-03-05",
                    "progress": 50,
                    "dependencies": "",
                    "custom_bar_color": "#001366",
                }
            ],
            "view_mode": "Week",
            "readonly": True,
        }
    )

    assert result == {
        "title": "Tender programme",
        "tasks": [
            {
                "id": "task_1",
                "name": "Scope review",
                "start": "2026-03-01",
                "end": "2026-03-05",
                "progress": 50.0,
                "custom_bar_color": "#001366",
            }
        ],
        "view_mode": "Week",
        "readonly": True,
    }
