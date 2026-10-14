import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infra_reports.config import ConfigError, load_settings, parse_recipients, read_env_file
from infra_reports.tb_client import ThingsBoardClient


def write_env(text):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


class ConfigTest(unittest.TestCase):
    def test_parse_recipients(self):
        self.assertEqual(parse_recipients("a@x.com, b@y.org;c@z.in"), ["a@x.com", "b@y.org", "c@z.in"])
        self.assertEqual(parse_recipients(""), [])
        with self.assertRaises(ConfigError):
            parse_recipients("a@x.com, not-an-email")

    def test_read_env_file(self):
        path = write_env("# comment\nA=1\nB = 'two'\n\nC=\"x=y\"\nbad line\n")
        self.assertEqual(read_env_file(path), {"A": "1", "B": "two", "C": "x=y"})

    def test_file_wins_and_process_env_is_untouched(self):
        path = write_env("SMTP_USER=file@x.com\nREPORT_RECIPIENTS=a@x.com\nTB_TENANT_ID=t1\n")
        with mock.patch.dict(os.environ, {"SMTP_USER": "env@x.com", "SMTP_HOST": "smtp.env"}, clear=False):
            settings = load_settings(path)
            self.assertEqual(settings.smtp_user, "file@x.com")
            self.assertEqual(settings.smtp_host, "smtp.env")  # fallback to the process env
            self.assertEqual(os.environ["SMTP_USER"], "env@x.com")
            self.assertNotIn("TB_TENANT_ID", os.environ)
        self.assertEqual(settings.recipients, ["a@x.com"])
        self.assertEqual(settings.profiles["dg"], ["woodward_kg1500"])

    def test_no_hardcoded_credentials(self):
        path = write_env("")
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings(path)
        self.assertEqual((settings.tb_sysadmin_user, settings.tb_sysadmin_pass, settings.recipients), ("", "", []))
        with self.assertRaises(ConfigError):
            ThingsBoardClient.connect(settings, session=mock.Mock())


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._data


class ClientTest(unittest.TestCase):
    def make_client(self, responses):
        session = mock.Mock()
        session.get.side_effect = [FakeResponse(r) for r in responses]
        return ThingsBoardClient("http://tb", session), session

    def test_devices_follow_pagination(self):
        client, session = self.make_client([
            {"data": [{"name": "a"}], "hasNext": True},
            {"data": [{"name": "b"}], "hasNext": False},
        ])
        self.assertEqual([d["name"] for d in client.devices()], ["a", "b"])
        self.assertEqual([c.kwargs["params"]["page"] for c in session.get.call_args_list], [0, 1])

    def test_active_alarms_use_search_status(self):
        client, session = self.make_client([{"data": [{"type": "X"}], "hasNext": False}])
        self.assertEqual(len(client.alarms("d1", active_only=True)), 1)
        self.assertEqual(session.get.call_args.kwargs["params"]["searchStatus"], "ACTIVE")

    def test_http_error_raises(self):
        client, _ = self.make_client([])
        client.session.get.side_effect = [FakeResponse({"message": "bad"}, status=400)]
        with self.assertRaises(RuntimeError):
            client.devices()

    def test_sysadmin_login_requires_tenant_id(self):
        path = write_env("TB_SYSADMIN_USER=s\nTB_SYSADMIN_PASS=p\n")
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings(path)
        with self.assertRaises(ConfigError):
            ThingsBoardClient.connect(settings, session=mock.Mock())


if __name__ == "__main__":
    unittest.main()
