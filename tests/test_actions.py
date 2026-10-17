"""M13 A6 rider notices and A7 GitHub dossier tickets (with fake transports: nothing is ever sent or filed here)."""
import pytest

from lastlift import db, seed, state, tools
from lastlift.agents import notify, roles, tickets
from lastlift.config import settings

pytestmark = pytest.mark.skipif(not db.ping(), reason="FalkorDB not reachable")


class Sent:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        return type("R", (), {"status_code": 200})()


@pytest.fixture(scope="module")
def demo():
    assert seed.main(["--if-missing"]) == 0
    tools.prepare_scope("demo")
    db.client().select_graph(state.graph_name("demo")).query("MATCH (n:Notice) DETACH DELETE n")
    return "demo"


def test_one_notice_per_state_change_none_on_a_no_op(demo):
    t = Sent()
    lost = [{"platform": "Wonderland platform", "dir": "board"}]
    r1 = notify.publish(demo, "place-rbmnl", lost, ["885"], t, now=1000)
    r2 = notify.publish(demo, "place-rbmnl", lost, ["885"], t, now=1100)
    assert r1["sent"] and r1["kind"] == "loss" and not r2["sent"] and r2["reason"] == "no change"
    r3 = notify.publish(demo, "place-rbmnl", [], [], t, now=1200)          # lift back: one restore notice
    assert r3["sent"] and r3["kind"] == "restore" and "885" in r3["body"]
    assert not notify.publish(demo, "place-rbmnl", [], [], t, now=1300)["sent"]
    assert len(t.calls) == 2
    url, kw = t.calls[0]
    assert url == f"https://ntfy.sh/{notify.topic('place-rbmnl')}" and kw["headers"]["Tags"] == "wheelchair"
    assert notify.lint(r1["body"]) == [] and notify.lint(r3["body"]) == []


def test_notices_are_a_dry_run_by_default(demo, monkeypatch):
    monkeypatch.delenv("NOTIFY_MODE", raising=False)
    r = notify.publish(demo, "place-chncl", [{"platform": "Oak Grove platform", "dir": "exit"}], ["876"])
    assert r["dry_run"] is True and r["sent"] is False


class FakeGitHub:
    """Records requests; the first search finds nothing, later ones find the issue it created."""

    def __init__(self):
        self.created, self.comments, self.issue = [], [], None

    def get(self, url, headers=None, params=None):
        items = [self.issue] if self.issue else []
        return type("R", (), {"json": lambda s: {"items": items}})()

    def post(self, url, headers=None, json=None):
        if url.endswith("/comments"):
            self.comments.append(json)
            return type("R", (), {"status_code": 201, "json": lambda s: {}})()
        self.created.append(json)
        self.issue = {"url": "https://api.github.com/repos/x/y/issues/1", "html_url": "https://github.com/x/y/issues/1",
                      "body": json["body"]}
        return type("R", (), {"status_code": 201, "json": lambda s: {"html_url": self.issue["html_url"]}})()


def test_double_submit_files_one_issue_and_one_comment(demo, monkeypatch):
    monkeypatch.setattr(tickets, "settings", type(settings)(**{**settings.__dict__, "actions_mode": "file",
                                                                "github_token": "test-token"}))
    gh = FakeGitHub()
    p = {"facility_id": "885", "kind": "repair_ticket", "playbook": "ACCESS_LOST", "label": "priority-1"}
    first = tickets.file(demo, p, gh)
    second = tickets.file(demo, p, gh)
    assert first["action"] == "create" and second["action"] == "comment"
    assert len(gh.created) == 1 and len(gh.comments) == 1
    assert "<!-- lastlift:key=lift-885:ACCESS_LOST -->" in gh.created[0]["body"] and "lift-885" in gh.created[0]["labels"]


def test_draft_mode_never_files_and_mermaid_is_well_formed(demo):
    d = tickets.file(demo, {"facility_id": "885", "kind": "repair_ticket", "playbook": "ACCESS_LOST",
                            "label": "priority-1"})
    assert d["mode"] == "draft" and d["action"] == "none"
    m = tickets.mermaid("place-rbmnl", demo, "885")
    lines = m.splitlines()
    assert lines[0] == "flowchart TB"
    nodes = [ln for ln in lines if '["' in ln]
    edges = [ln for ln in lines if "-->" in ln or "-.->" in ln]
    assert 0 < len(nodes) <= tickets.MAX_NODES and edges
    for ln in lines:
        if ln.strip().startswith("linkStyle"):
            assert all(int(i) < len(edges) for i in ln.split()[1].split(","))
    assert "```mermaid" in d["issue"]["body"] and roles.POLICY["repair_ticket"]["approval"] == "human"
