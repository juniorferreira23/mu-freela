import unittest
from unittest.mock import Mock, patch

import main


class ResolverAntiCaptchaTests(unittest.TestCase):
    @patch("main.hCaptchaProxyless")
    def test_no_slot_available_is_recoverable(self, solver_class):
        solver = Mock(
            spec_set=[
                "set_verbose",
                "set_key",
                "set_website_url",
                "set_website_key",
                "solve_and_return_solution",
                "error_code",
                "err_string",
            ]
        )
        solver_class.return_value = solver
        solver.solve_and_return_solution.return_value = 0
        solver.error_code = "ERROR_NO_SLOT_AVAILABLE"
        solver.err_string = "API error ERROR_NO_SLOT_AVAILABLE"

        resposta, sem_saldo = main.resolver_via_anticaptcha(
            "https://captcha.example", "sitekey", "api-key"
        )

        self.assertIsNone(resposta)
        self.assertFalse(sem_saldo)

    @patch("main.hCaptchaProxyless")
    def test_zero_balance_is_detected_from_error_code(self, solver_class):
        solver = solver_class.return_value
        solver.solve_and_return_solution.return_value = 0
        solver.error_code = "ERROR_ZERO_BALANCE"
        solver.err_string = "API error ERROR_ZERO_BALANCE"

        resposta, sem_saldo = main.resolver_via_anticaptcha(
            "https://captcha.example", "sitekey", "api-key"
        )

        self.assertIsNone(resposta)
        self.assertTrue(sem_saldo)

    @patch("main.hCaptchaProxyless")
    def test_solver_exception_is_recoverable(self, solver_class):
        solver_class.return_value.solve_and_return_solution.side_effect = RuntimeError(
            "service unavailable"
        )

        resposta, sem_saldo = main.resolver_via_anticaptcha(
            "https://captcha.example", "sitekey", "api-key"
        )

        self.assertIsNone(resposta)
        self.assertFalse(sem_saldo)


class ResolverTwoCaptchaTests(unittest.TestCase):
    @patch("main.TwoCaptcha", side_effect=RuntimeError("service unavailable"))
    def test_two_captcha_constructor_exception_does_not_stop_process(self, solver_class):
        resposta = main.resolver_via_2captcha(
            "https://captcha.example", "sitekey", "api-key"
        )

        self.assertIsNone(resposta)

    @patch("main.TwoCaptcha")
    def test_two_captcha_exception_does_not_stop_process(self, solver_class):
        solver_class.return_value.hcaptcha.side_effect = RuntimeError(
            "service unavailable"
        )

        resposta = main.resolver_via_2captcha(
            "https://captcha.example", "sitekey", "api-key"
        )

        self.assertIsNone(resposta)

    @patch("main.TwoCaptcha")
    def test_unexpected_two_captcha_response_is_recoverable(self, solver_class):
        solver_class.return_value.hcaptcha.return_value = {}

        resposta = main.resolver_via_2captcha(
            "https://captcha.example", "sitekey", "api-key"
        )

        self.assertIsNone(resposta)


class RetryTests(unittest.TestCase):
    def test_retry_interval_grows_until_limit(self):
        self.assertEqual(
            main.proximo_intervalo_retry(main.INTERVALO_SEGUNDOS), 15
        )
        self.assertEqual(main.proximo_intervalo_retry(15), 30)
        self.assertEqual(
            main.proximo_intervalo_retry(main.INTERVALO_RETRY_MAX_SEGUNDOS),
            main.INTERVALO_RETRY_MAX_SEGUNDOS,
        )

    @patch("main.resolver_via_anticaptcha", return_value=(None, True))
    def test_missing_fallback_key_keeps_captcha_pending(self, resolver):
        pagina = Mock()
        pagina.url = "https://captcha.example/?sitekey=sitekey"

        resultado = main.resolver_captcha(pagina, "api-key", None)

        self.assertFalse(resultado)
        resolver.assert_called_once()


if __name__ == "__main__":
    unittest.main()
