import pytest
from src.eval.app_mode import AppMode
from src.workflows.factory import get_workflow


@pytest.fixture
def shadow_writer(mocker):
    shadow_writer_constructor = mocker.patch("src.workflows.factory.ShadowGmailWriter")
    return shadow_writer_constructor


@pytest.fixture
def gmail_writer(mocker):
    gmail_writer_constructor = mocker.patch("src.workflows.factory.GmailWriter")
    return gmail_writer_constructor


@pytest.fixture
def gmail_reader(mocker):
    gmail_reader_constructor = mocker.patch("src.workflows.factory.GmailReader")
    return gmail_reader_constructor


@pytest.fixture
def agent_schema(mocker):
    agent_schema_constructor = mocker.patch("src.workflows.factory.AgentSchema", autospec=True)
    return agent_schema_constructor


@pytest.fixture
def agent(mocker, agent_schema):
    agent_constructor = mocker.patch("src.workflows.factory.Agent", autospec=True)
    return agent_constructor


@pytest.fixture
def slack_app(mocker):
    return mocker.Mock()


def test_shadow_mode_selects_shadow_writer(mocker, slack_app, agent, shadow_writer, gmail_writer, gmail_reader):
    mocker.patch("src.workflows.factory.AppMode.get_app_mode", return_value=AppMode.SHADOW)
    workflow = get_workflow(slack_app)
    assert workflow.gmail_writer is shadow_writer.return_value
    gmail_writer.assert_not_called()
    assert workflow.gmail_writer is workflow.draft_handler.gmail_writer


def test_live_mode_selects_gmail_writer(mocker, slack_app, agent, shadow_writer, gmail_writer, gmail_reader):
    mocker.patch("src.workflows.factory.AppMode.get_app_mode", return_value=AppMode.LIVE)
    workflow = get_workflow(slack_app)
    assert workflow.gmail_writer is gmail_writer.return_value
    shadow_writer.assert_not_called()
    assert workflow.gmail_writer is workflow.draft_handler.gmail_writer
