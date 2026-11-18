from odoo import models
from ..exceptions import OperatorNotAvailable


class SaasTemplate(models.Model):
    _inherit = "saas.template"

    def _random_ready_operator_id(self):
        self.ensure_one()
        template_operators = self.sudo().operator_ids
        if not template_operators:
            raise OperatorNotAvailable(self.env._('No template operators are configured. Contact the administrator.'))

        template_operator = template_operators.random_ready_operator()
        if not template_operator:
            raise OperatorNotAvailable(self.env._('No operators are ready. Please try again later.'))

        return template_operator.operator_id.id
