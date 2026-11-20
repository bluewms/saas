from odoo import api, models, fields


class SaasTemplate(models.Model):
    _name = "saas.template"
    _inherit = ["saas.template", "saas.period.product.mixin"]

    is_package = fields.Boolean("Is package?")
    package_image = fields.Image(
        string='Package image'
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Packages need their sale product and variants on creation as well as
        # on later edits. Price inverses run before the product is linked.
        records.write({})
        for record, vals in zip(records, vals_list):
            prices = {key: vals[key] for key in ('month_price', 'year_price') if key in vals}
            if prices and record.is_package:
                record.write(prices)
        return records

    def write(self, vals):
        res = super(SaasTemplate, self).write(vals)

        ProductTemplate = self.env["product.template"].sudo().with_context(active_test=False)
        for record in self:
            if record.is_package and not record.product_tmpl_id:
                product_tmpl_id = ProductTemplate.search([("saas_package_id", "=", record.id)])
                if not product_tmpl_id:
                    product_tmpl_id = ProductTemplate.create({
                        "name": record.name,
                        "image_1920": record.package_image,
                        "saas_package_id": record.id,
                        "is_saas_product": True,
                        "website_published": True,
                        "list_price": 0,
                    })
                else:
                    product_tmpl_id.write({"active": True})
                record.product_tmpl_id = product_tmpl_id

        return res
