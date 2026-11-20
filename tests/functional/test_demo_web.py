"""Live ADK Web checks; set ADK_DEMO_URL to an already-running demo."""
from __future__ import annotations

import base64
import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.oracle


@pytest.fixture
def demo_client():
  base = os.environ.get("ADK_DEMO_URL")
  if not base:
    pytest.skip("Set ADK_DEMO_URL to run the live demo API checks")
  with httpx.Client(base_url=base, timeout=120, trust_env=False) as client:
    yield client


@pytest.fixture
def demo_session(demo_client):
  created = []

  def create(app):
    user = "demo-test-" + uuid.uuid4().hex
    response = demo_client.post(f"/apps/{app}/users/{user}/sessions",
                               json={"state": {"demo_validation": True}})
    response.raise_for_status()
    session = response.json()
    path = f"/apps/{app}/users/{user}/sessions/{session['id']}"
    created.append(path)
    return app, user, session["id"], path

  yield create
  for path in reversed(created):
    artifacts = demo_client.get(path + "/artifacts")
    artifacts.raise_for_status()
    for filename in artifacts.json():
      response = demo_client.delete(path + "/artifacts/" + filename)
      response.raise_for_status()
    response = demo_client.delete(path)
    response.raise_for_status()


def _run(client, app, user, session, prompt):
  events = []
  with client.stream("POST", "/run_sse", json={
      "appName": app, "userId": user, "sessionId": session, "streaming": True,
      "newMessage": {"role": "user", "parts": [{"text": prompt}]},
  }) as response:
    response.raise_for_status()
    for line in response.iter_lines():
      if line.startswith("data:"):
        import json
        event = json.loads(line[5:].strip())
        assert not event.get("error"), event
        assert not event.get("errorCode"), event
        events.append(event)
  assert events
  return events


def test_demo_lists_both_agents(demo_client):
  response = demo_client.get("/list-apps")
  response.raise_for_status()
  assert {"oracle_runtime_agent", "oracle_travel_agent"} <= set(response.json())


def test_demo_session_state_persists(demo_client, demo_session):
  app, user, session, path = demo_session("oracle_runtime_agent")
  response = demo_client.get(path)
  response.raise_for_status()
  assert response.json()["state"]["demo_validation"] is True
  listed = demo_client.get(f"/apps/{app}/users/{user}/sessions")
  listed.raise_for_status()
  assert session in {s["id"] for s in listed.json()}


def test_runtime_demo_streams_and_persists_a_reply(demo_client, demo_session):
  app, user, session, path = demo_session("oracle_runtime_agent")
  events = _run(demo_client, app, user, session,
                "What is 19 plus 23? Reply with only the decimal integer.")
  text = "".join(part.get("text", "") for event in events if not event.get("partial")
                 for part in event.get("content", {}).get("parts", []) if not part.get("thought"))
  assert text.strip() == "42"
  loaded = demo_client.get(path)
  loaded.raise_for_status()
  assert len(loaded.json()["events"]) >= 2


def test_travel_demo_creates_loadable_pdf_and_companion(demo_client, demo_session):
  app, user, session, path = demo_session("oracle_travel_agent")
  marker = "ORACLE-WEB-" + uuid.uuid4().hex[:10].upper()
  body = marker + ". Morning: garden walk. Afternoon: vegetarian lunch."
  events = _run(demo_client, app, user, session,
      'Generate a PDF named web_demo.pdf titled Oracle OCI Demo using exactly this '
      'itinerary text: "' + body + '". Use the PDF generation tool, then list my artifacts.')
  calls = [part["functionCall"]["name"] for event in events
           for part in event.get("content", {}).get("parts", []) if part.get("functionCall")]
  assert "generate_and_save_itinerary_pdf" in calls
  listed = demo_client.get(path + "/artifacts")
  listed.raise_for_status()
  assert {"web_demo.pdf", "web_demo.txt"} <= set(listed.json())
  pdf = demo_client.get(path + "/artifacts/web_demo.pdf")
  pdf.raise_for_status()
  part = pdf.json()
  blob = part.get("inlineData") or part.get("inline_data")
  assert blob is not None
  assert base64.b64decode(blob["data"]).startswith(b"%PDF")
  text = demo_client.get(path + "/artifacts/web_demo.txt")
  text.raise_for_status()
  assert marker in text.json()["text"]
  versions = demo_client.get(path + "/artifacts/web_demo.pdf/versions")
  versions.raise_for_status()
  assert versions.json() == [0]
