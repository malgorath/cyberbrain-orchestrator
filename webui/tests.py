from django.test import TestCase
from orchestrator.models import Directive, Run


class WebUILayoutTests(TestCase):
    def setUp(self):
        directive = Directive.objects.create(name='default')
        self.run = Run.objects.create(directive=directive)

    def _assert_base_layout(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="container"')
        self.assertContains(response, 'class="content"')
        self.assertContains(response, 'nav-links')

    def test_key_pages_share_base_layout(self):
        urls = [
            '/',
            '/runs/',
            f'/runs/{self.run.id}/',
            '/directives/',
            '/worker-hosts/',
            '/schedules/',
            '/tasks/',
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self._assert_base_layout(response)
