"""A delete waits 30 days; tests that need the record gone ask for it and erase it at once (the tenant's and
MYTech's administrators hold `delete.permanent`)."""
from types import SimpleNamespace


def delete_now(client, h, path):
    """-> the refusal of the delete request, or {"result": "deleted" | "deactivated"} after erasing it."""
    r = client.delete(path, headers=h)
    if r.status_code != 200:
        return r
    assert r.json()["result"] == "scheduled", r.text
    done = client.post(f"/api/v1/deletions/{r.json()['request_id']}/now", headers=h)
    if done.status_code != 200:
        return done
    body = {"result": done.json()["note"]}
    return SimpleNamespace(status_code=200, json=lambda: body, text=str(body))
