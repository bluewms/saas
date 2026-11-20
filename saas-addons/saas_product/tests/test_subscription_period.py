from datetime import datetime

from odoo.addons.base.tests.common import BaseCommon
from odoo.tests.common import tagged


@tagged('post_install', '-at_install')
class TestSubscriptionPeriod(BaseCommon):
    def test_monthly_subscription_uses_calendar_month(self):
        product = self.env.ref('saas_product.product_users_monthly')
        self.assertEqual(datetime(2026, 1, 31, 12) + product._get_expiration_timedelta(), datetime(2026, 2, 28, 12))

    def test_yearly_subscription_handles_leap_day(self):
        product = self.env.ref('saas_product.product_users_annually')
        self.assertEqual(datetime(2024, 2, 29, 12) + product._get_expiration_timedelta(), datetime(2025, 2, 28, 12))
