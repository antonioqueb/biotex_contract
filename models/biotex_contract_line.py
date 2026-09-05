from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.biotex_base.models.integrity import lock_records


class BiotexContractLine(models.Model):
    """Clave del contrato: lo que la institución licitó. Lo entregado puede ser otro producto (máscara)."""
    _name = 'biotex.contract.line'
    _description = 'Clave de contrato'
    _order = 'contract_id, sequence, id'

    contract_id = fields.Many2one('biotex.contract', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    partner_id = fields.Many2one(related='contract_id.partner_id', store=True)
    state = fields.Selection(related='contract_id.state', store=True)
    sequence = fields.Integer(default=10)
    part_number = fields.Char(string='Partida institucional')
    institutional_version = fields.Char(string='Versión del catálogo institucional')
    product_ids = fields.Many2many('product.product', string='Correspondencias de catálogo')
    amount_applied = fields.Monetary(string='Aplicación administrativa', default=0, readonly=True)
    code = fields.Char(string='Clave institución', required=True, help='Clave del cuadro básico / partida licitada.')
    name = fields.Char(string='Descripción de la clave', required=True)
    product_id = fields.Many2one(
        'product.product', string='Producto de catálogo',
        help='Producto propio que normalmente cubre esta clave. Puede entregarse otro (máscara).')
    uom_id = fields.Many2one('uom.uom', string='Unidad')
    product_qty = fields.Float(string='Cantidad contratada', required=True, default=1.0)
    price_unit = fields.Float(string='Precio unitario', required=True, digits='Product Price')
    amount = fields.Monetary(string='Importe', compute='_compute_amount', store=True)
    qty_delivered = fields.Float(string='Remisionado', compute='_compute_delivered', store=True)
    qty_invoiced = fields.Float(string='Facturado', compute='_compute_delivered', store=True)
    qty_remaining = fields.Float(string='Pendiente', compute='_compute_delivered', store=True)
    amount_delivered = fields.Monetary(compute='_compute_delivered', store=True)
    amount_invoiced = fields.Monetary(compute='_compute_delivered', store=True)
    progress = fields.Float(string='Avance %', compute='_compute_delivered', store=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('code', 'name', 'qty_remaining')
    def _compute_display_name(self):
        for l in self:
            l.display_name = '%s - %s' % (l.code or '', l.name or '')

    @api.depends('product_qty', 'price_unit')
    def _compute_amount(self):
        for l in self:
            l.amount = l.product_qty * l.price_unit

    # Los módulos de remisión extienden este cómputo; aquí solo la base.
    def _get_delivered_values(self):
        """Regresa (qty_delivered, qty_invoiced). Sobrescrito por biotex_remision."""
        return 0.0, 0.0

    @api.depends('product_qty', 'price_unit')
    def _compute_delivered(self):
        for l in self:
            qty_delivered, qty_invoiced = l._get_delivered_values()
            l.qty_delivered = qty_delivered
            l.qty_invoiced = qty_invoiced
            l.qty_remaining = l.product_qty - qty_delivered
            l.amount_delivered = qty_delivered * l.price_unit
            l.amount_invoiced = qty_invoiced * l.price_unit
            l.progress = (qty_delivered / l.product_qty * 100.0) if l.product_qty else 0.0

    @api.onchange('product_id')
    def _onchange_product(self):
        for l in self:
            if l.product_id:
                l.name = l.name or l.product_id.name
                l.uom_id = l.product_id.uom_id
                if l.contract_id.pricelist_id:
                    l.price_unit = l.contract_id.pricelist_id._get_product_price(l.product_id, l.product_qty or 1.0)
                else:
                    l.price_unit = l.price_unit or l.product_id.list_price

    @api.model_create_multi
    def create(self, vals_list):
        parents = self.env['biotex.contract'].browse([v['contract_id'] for v in vals_list if v.get('contract_id')])
        lock_records(parents)
        if any(c.state != 'draft' for c in parents):
            raise UserError('Los renglones confirmados requieren una modificación documentada.')
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) & {'contract_id', 'part_number', 'code', 'name', 'uom_id', 'product_id', 'product_ids', 'product_qty', 'price_unit'}:
            lock_records(self.contract_id)
            if any(c.state != 'draft' for c in self.contract_id):
                raise UserError('Los renglones confirmados conservan su contenido y precio.')
        return super().write(vals)

    def unlink(self):
        lock_records(self.contract_id)
        if any(c.state != 'draft' for c in self.contract_id):
            raise UserError('No se borran renglones del contrato confirmado.')
        return super().unlink()
