from glanceflow.agent.clarification import ClarificationPolicy


def test_minimal_question_priority_and_recapture():
    policy = ClarificationPolicy()
    request = policy.choose(["location", "event_start"], {}, [])
    assert request.field == "event_start" and "时间" in request.question
    recapture = policy.choose(["location"], {}, ["poor_image_quality"])
    assert recapture.request_recapture is True


def test_same_question_has_two_round_limit():
    policy = ClarificationPolicy()
    assert policy.choose(["location"], {"location": 1}, []).exhausted is False
    assert policy.choose(["location"], {"location": 2}, []).exhausted is True
