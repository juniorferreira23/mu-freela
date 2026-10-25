import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import main_2captcha as solver


class TwoCaptchaApiTests(unittest.TestCase):
    def test_payload_targets_hcaptcha_using_v2_task(self):
        payload = solver.criar_payload_hcaptcha(
            "test-api-key",
            "https://captcha.example/?sitekey=test-sitekey",
            "test-sitekey",
        )

        self.assertEqual(payload["clientKey"], "test-api-key")
        self.assertEqual(payload["task"]["type"], "HCaptchaTaskProxyless")
        self.assertEqual(
            payload["task"]["websiteURL"],
            "https://captcha.example/?sitekey=test-sitekey",
        )
        self.assertEqual(payload["task"]["websiteKey"], "test-sitekey")

    @patch("main_2captcha.time.sleep")
    @patch("main_2captcha.postar_json")
    def test_creates_one_task_polls_and_returns_solution(self, postar_json, sleep):
        postar_json.side_effect = [
            {"errorId": 0, "taskId": 731},
            {"errorId": 0, "status": "processing"},
            {
                "errorId": 0,
                "status": "ready",
                "solution": {"gRecaptchaResponse": "test-hcaptcha-token"},
            },
        ]

        token = solver.resolver_via_2captcha(
            "https://captcha.example/?sitekey=test-sitekey",
            "test-sitekey",
            "test-api-key",
        )

        self.assertEqual(token, "test-hcaptcha-token")
        metodos = [chamada.args[0] for chamada in postar_json.call_args_list]
        self.assertEqual(metodos, ["createTask", "getTaskResult", "getTaskResult"])
        self.assertEqual(metodos.count("createTask"), 1)
        sleep.assert_called_once_with(solver.INTERVALO_POLL_SEGUNDOS)

    @patch("main_2captcha.registrar_excecao")
    @patch("main_2captcha.postar_json")
    def test_api_error_returns_none_without_creating_another_task(
        self, postar_json, registrar_excecao
    ):
        postar_json.return_value = {
            "errorId": 1,
            "errorCode": "ERROR_KEY_DOES_NOT_EXIST",
            "errorDescription": "invalid key",
        }

        token = solver.resolver_via_2captcha(
            "https://captcha.example/?sitekey=test-sitekey",
            "test-sitekey",
            "test-api-key",
        )

        self.assertIsNone(token)
        postar_json.assert_called_once()
        self.assertEqual(postar_json.call_args.args[0], "createTask")
        registrar_excecao.assert_called_once()

    def test_extract_token_rejects_solution_without_token(self):
        with self.assertRaisesRegex(RuntimeError, "token reconhecido"):
            solver.extrair_token({"solution": {"otherField": "value"}})

    def test_frozen_executable_prefers_dotenv_beside_exe(self):
        with TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "dist"
            app_dir.mkdir()
            adjacent_dotenv = app_dir / ".env"
            adjacent_dotenv.touch()
            (Path(temp_dir) / ".env").touch()

            with (
                patch.object(solver.sys, "frozen", True, create=True),
                patch.object(solver.sys, "executable", str(app_dir / "app.exe")),
            ):
                self.assertEqual(
                    solver.localizar_arquivo_dotenv(), adjacent_dotenv.resolve()
                )

    def test_frozen_executable_falls_back_to_project_root_dotenv(self):
        with TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "dist"
            app_dir.mkdir()
            root_dotenv = Path(temp_dir) / ".env"
            root_dotenv.touch()

            with (
                patch.object(solver.sys, "frozen", True, create=True),
                patch.object(solver.sys, "executable", str(app_dir / "app.exe")),
            ):
                self.assertEqual(
                    solver.localizar_arquivo_dotenv(), root_dotenv.resolve()
                )

    @patch("main_2captcha.input")
    @patch("main_2captcha.main", return_value=1)
    def test_packaged_executable_waits_for_enter_before_closing(
        self, main, input_prompt
    ):
        with patch.object(solver.sys, "frozen", True, create=True):
            codigo_saida = solver.executar()

        self.assertEqual(codigo_saida, 1)
        main.assert_called_once_with()
        input_prompt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
