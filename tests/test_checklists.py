"""Tests for checklist management in tasks (TipTap taskList parser & handlers)."""
import pytest
from _task_checklist import (
    _parse_checklist,
    _toggle_checklist_item,
    _add_checklist_item,
    _delete_checklist_item,
    _strip_tasklist,
)
from handlers_crud import (
    get_checklist,
    add_checklist_item,
    toggle_checklist_item,
    delete_checklist_item,
    GetChecklistParams,
    AddChecklistItemParams,
    ToggleChecklistItemParams,
    DeleteChecklistItemParams,
)


class MockUser:
    imperal_id = "test_user_checklist"


class MockContext:
    def __init__(self, task_data):
        self.user = MockUser()
        self.task_data = task_data
        self.posted = []

    class HttpMock:
        def __init__(self, parent):
            self.parent = parent

        async def get(self, url, params=None, headers=None):
            class Resp:
                ok = True
                body = self.parent.task_data
            return Resp()

        async def post(self, url, json=None, headers=None):
            self.parent.posted.append(json)
            # update task_data with new description if posted
            if json and "description" in json:
                self.parent.task_data["description"] = json["description"]
            class Resp:
                ok = True
                body = self.parent.task_data
            return Resp()

    @property
    def http(self):
        return self.HttpMock(self)

    class SecretsMock:
        async def get(self, key):
            return "mock_key"

    @property
    def secrets(self):
        return self.SecretsMock()


def test_checklist_parser_pure():
    html = '<p>Some intro</p><ul data-type="taskList"><li data-type="taskItem" data-checked="false"><div>Item 1</div></li><li data-type="taskItem" data-checked="true"><div>Item 2</div></li></ul>'
    items = _parse_checklist(html)
    assert len(items) == 2
    assert items[0] == {"checked": False, "text": "Item 1"}
    assert items[1] == {"checked": True, "text": "Item 2"}

    toggled = _toggle_checklist_item(html, 0, True)
    assert 'data-checked="true"><div>Item 1</div>' in toggled

    added = _add_checklist_item(html, "Item 3", False)
    assert '<div>Item 3</div>' in added
    assert len(_parse_checklist(added)) == 3

    deleted, ok = _delete_checklist_item(added, 1)
    assert ok is True
    assert len(_parse_checklist(deleted)) == 2
    assert "Item 2" not in deleted

    stripped = _strip_tasklist(html)
    assert stripped == "<p>Some intro</p>"


@pytest.mark.asyncio
async def test_get_and_add_checklist_handler(monkeypatch):
    monkeypatch.setenv("VIKUNJA_BRIDGE_URL", "http://bridge.local")
    initial_desc = '<p>Notes</p><ul data-type="taskList"><li data-type="taskItem" data-checked="false"><div>First item</div></li></ul>'
    task = {"id": 101, "title": "Test Task", "description": initial_desc}
    ctx = MockContext(task)

    # 1. get_checklist
    res_get = await get_checklist(ctx, GetChecklistParams(task_id=101))
    assert res_get.status == "success"
    data_get = res_get.data
    assert data_get["total"] == 1
    assert data_get["items"][0]["text"] == "First item"
    assert data_get["items"][0]["checked"] is False

    # 2. add_checklist_item
    res_add = await add_checklist_item(ctx, AddChecklistItemParams(task_id=101, text="Second item", checked=True))
    assert res_add.status == "success"
    assert res_add.data["total"] == 2
    assert res_add.data["item_index"] == 1
    assert res_add.data["checked"] is True

    # 3. toggle_checklist_item
    res_toggle = await toggle_checklist_item(ctx, ToggleChecklistItemParams(task_id=101, item_index=0, checked=True))
    assert res_toggle.status == "success"
    assert res_toggle.data["checked"] is True

    # 4. delete_checklist_item
    res_del = await delete_checklist_item(ctx, DeleteChecklistItemParams(task_id=101, item_index=1))
    assert res_del.status == "success"
    assert res_del.data["total"] == 1
