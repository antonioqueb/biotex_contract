from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.biotex_base.models.integrity import guard_create, guard_write, lock_records, require_group, transition


class BiotexContract(models.Model):
    """Contrato / partida ganada (R32). El avance se controla por MONTO (regla 8) y, de forma informativa, por clave."""
    _name = 'biotex.contract'
    _description = 'Contrato'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Número de contrato', required=True, tracking=True, copy=False)
    display_name = fields.Char(compute='_compute_display_name', store=True)
    contract_type = fields.Selection([
        ('tender', 'Licitación'),
        ('direct', 'Compra directa / emergente'),
        ('private', 'Cliente privado'),
    ], required=True, default='tender', tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Institución / cliente', required=True, tracking=True,
        domain=[('biotex_partner_type', 'in', ('institution', 'private'))])
    company_id = fields.Many2one(
        'res.company', string='Razón social que factura', required=True, tracking=True,
        default=lambda self: self.env.company,
        help='La remisión y la factura se emiten con esta razón social (R30).')
    warehouse_ids = fields.Many2many(
        'stock.warehouse', 'biotex_contract_warehouse_rel', 'contract_id', 'warehouse_id',
        string='Delegaciones que atienden', help='Se precarga en la solicitud de compra según delegación (R07).')
    responsible_id = fields.Many2one('res.users', string='Responsable', default=lambda self: self.env.user, tracking=True)
    date_start = fields.Date(string='Inicio de vigencia', tracking=True)
    date_end = fields.Date(string='Fin de vigencia', tracking=True)
    delivery_mode = fields.Selection([
        ('on_request', 'Bajo solicitud'), ('monthly', 'Entregas mensuales'), ('calendar', 'Por calendario'), ('total', 'Entrega total')],
        string='Modalidad de entrega')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    pricelist_id = fields.Many2one('product.pricelist', string='Lista de precios', check_company=True)
    line_ids = fields.One2many('biotex.contract.line', 'contract_id', string='Claves', copy=True)
    state = fields.Selection([
        ('draft', 'Borrador'), ('active', 'Vigente'), ('expired', 'Vencido'), ('closed', 'Cerrado'), ('cancelled', 'Cancelado')],
        default='draft', tracking=True, index=True)

    hospital_ids = fields.Many2many('res.partner', string='Destinos autorizados', tracking=True)
    external_ref = fields.Char(string='Folio externo / evento', tracking=True)
    tax_basis = fields.Selection([('untaxed', 'Subtotal sin impuestos'), ('total', 'Total con impuestos')], default='untaxed', required=True, tracking=True)
    amendment_ids = fields.One2many('biotex.contract.amendment', 'contract_id', string='Modificaciones documentadas')
    effective_date_end = fields.Date(compute='_compute_effective_end')
    amount_applied = fields.Monetary(string='Aplicación administrativa', compute='_compute_amounts', store=True)

    # montos
    amount_contract = fields.Monetary(
        string='Monto del contrato', tracking=True,
        help='Si se deja en cero se toma la suma de las claves.')
    amount_total = fields.Monetary(string='Monto total', compute='_compute_amounts', store=True)
    amount_delivered = fields.Monetary(string='Remisionado', compute='_compute_amounts', store=True)
    amount_invoiced = fields.Monetary(string='Facturado', compute='_compute_amounts', store=True)
    amount_remaining = fields.Monetary(string='Saldo', compute='_compute_amounts', store=True)
    progress = fields.Float(string='Avance %', compute='_compute_amounts', store=True, aggregator='avg')
    tolerance_pct = fields.Float(
        string='Tolerancia de exceso %', default=0.0,
        help='Porcentaje sobre el monto que se permite exceder al remisionar. 0 = no se puede exceder.')
    alert_pct = fields.Float(string='Alertar al alcanzar %', default=0.0)
    alert_sent = fields.Boolean(copy=False)
    progress_data = fields.Json(compute='_compute_progress_data')
    notes = fields.Html()
    document_ids = fields.Many2many('ir.attachment', string='Documentos (contrato, fallo, anexos)')

    # -------------------------------------------------------------- computes
    @api.depends('name', 'partner_id.name', 'company_id.biotex_short_name')
    def _compute_display_name(self):
        for c in self:
            parts = [c.name or '', c.partner_id.name or '']
            if c.company_id.biotex_short_name:
                parts.append('[%s]' % c.company_id.biotex_short_name)
            c.display_name = ' - '.join(p for p in parts if p)

    @api.depends('amount_contract', 'line_ids.amount', 'line_ids.amount_delivered', 'line_ids.amount_invoiced', 'line_ids.amount_applied', 'amendment_ids.state', 'amendment_ids.amount_delta')
    def _compute_amounts(self):
        for c in self:
            lines_total = sum(c.line_ids.mapped('amount'))
            c.amount_total = c.amount_contract or lines_total
            c.amount_delivered = sum(c.line_ids.mapped('amount_delivered'))
            c.amount_invoiced = sum(c.line_ids.mapped('amount_invoiced'))
            c.amount_applied = sum(c.line_ids.mapped('amount_applied'))
            c.amount_remaining = c.amount_total - c.amount_applied
            c.progress = (c.amount_applied / c.amount_total * 100.0) if c.amount_total else 0.0

    def _compute_progress_data(self):
        for c in self:
            c.progress_data = {
                'amount_total': c.amount_total,
                'amount_delivered': c.amount_delivered,
                'amount_invoiced': c.amount_invoiced,
                'amount_remaining': c.amount_remaining,
                'progress': round(c.progress, 1),
                'alert_pct': c.alert_pct,
                'tolerance_pct': c.tolerance_pct,
                'currency': c.currency_id.symbol,
                'date_end': fields.Date.to_string(c.date_end) if c.date_end else '',
                'state': c.state,
                'lines': [{
                    'id': l.id, 'code': l.code, 'name': l.name, 'qty': l.product_qty,
                    'qty_delivered': l.qty_delivered, 'qty_remaining': l.qty_remaining,
                    'amount': l.amount, 'amount_delivered': l.amount_delivered,
                    'progress': round(l.progress, 1),
                } for l in c.line_ids],
            }

    # -------------------------------------------------------------- constraints
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for c in self:
            if c.date_start and c.date_end and c.date_end < c.date_start:
                raise ValidationError('La vigencia termina antes de iniciar.')

    @api.constrains('name', 'company_id')
    def _check_unique_name(self):
        for c in self:
            if self.search_count([('name', '=', c.name), ('company_id', '=', c.company_id.id), ('id', '!=', c.id)]):
                raise ValidationError('Ya existe el contrato %s en %s.' % (c.name, c.company_id.name))

    # -------------------------------------------------------------- reglas de consumo
    def check_can_consume(self, amount):
        """Valida que un monto adicional no exceda el contrato más la tolerancia."""
        self.ensure_one()
        lock_records(self)
        today = fields.Date.context_today(self)
        if not self.date_start or not self.effective_date_end or not self.date_start <= today <= self.effective_date_end:
            raise UserError('La fecha queda fuera de la vigencia documentada del contrato.')
        if self.state != 'active':
            raise UserError('El contrato %s no está vigente (%s).' % (self.name, dict(self._fields['state'].selection)[self.state]))
        limit = self.amount_total
        if self.currency_id.compare_amounts(self.amount_applied + amount, limit) > 0:
            raise UserError(
                'El contrato %s excedería su monto: total %.2f, remisionado %.2f, nuevo %.2f (tolerancia %.1f%%).'
                % (self.name, self.amount_total, self.amount_applied, amount, self.tolerance_pct))
        return True

    def _check_alerts(self):
        for c in self:
            if c.state == 'active' and c.alert_pct > 0 and not c.alert_sent and c.amount_total and c.progress >= c.alert_pct:
                c.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=c.responsible_id.id or self.env.uid,
                    summary='Contrato %s al %.0f%% del monto' % (c.name, c.progress),
                    note='Saldo disponible: %s %.2f. Revise entregas pendientes y renovación.' % (c.currency_id.symbol, c.amount_remaining))
                c.alert_sent = True
            elif c.progress < c.alert_pct and c.alert_sent:
                c.alert_sent = False

    def write(self, vals):
        guard_write(self, vals, ('state',), ('name', 'partner_id', 'company_id', 'date_start', 'date_end', 'line_ids', 'amount_contract', 'currency_id', 'tax_basis', 'hospital_ids'))
        res = super().write(vals)
        if 'alert_pct' in vals or 'amount_contract' in vals or 'line_ids' in vals:
            self._check_alerts()
        return res

    # -------------------------------------------------------------- acciones
    def action_activate(self):
        require_group(self, 'biotex_base.group_biotex_coordinator')
        lock_records(self)
        for c in self:
            if c.state == 'active':
                continue
            if c.state != 'draft' or not c.date_start or not c.date_end or not c.document_ids or not c.external_ref:
                raise UserError('Complete vigencia real, folio externo y documentos adjudicados antes de activar.')
            if not c.line_ids and not c.amount_contract:
                raise UserError('Capture las claves o el monto del contrato antes de activarlo.')
            transition(c, {'state': 'active'})
        return True

    def action_close(self):
        transition(self, {'state': 'closed'})

    def action_cancel(self):
        for c in self:
            if c.amount_delivered:
                raise UserError('No se puede cancelar un contrato con entregas remisionadas; ciérrelo.')
        transition(self, {'state': 'cancelled'})

    def action_draft(self):
        raise UserError('Conserve el contrato confirmado; registre una modificación documentada.')

    @api.model
    def _cron_expire(self):
        today = fields.Date.context_today(self)
        expired = self.search([('state', '=', 'active')]).filtered(lambda c: c.effective_date_end and c.effective_date_end < today)
        transition(expired, {'state': 'expired'})
        for c in expired:
            c.message_post(body='Contrato vencido automáticamente (fin de vigencia %s).' % c.date_end)
        self.search([('state', '=', 'active')])._check_alerts()

    @api.model
    def biotex_get_for_warehouse(self, warehouse_id, partner_id=None):
        """Contratos vigentes precargables para una delegación (R07)."""
        domain = [('state', '=', 'active'), '|', ('warehouse_ids', '=', False), ('warehouse_ids', 'in', [warehouse_id])]
        if partner_id:
            domain.append(('partner_id', '=', partner_id))
        return self.search(domain)

    def _compute_effective_end(self):
        for contract in self:
            changes = contract.amendment_ids.filtered(lambda a: a.state == 'approved' and a.date_end).sorted('id')
            contract.effective_date_end = changes[-1].date_end if changes else contract.date_end

    @api.model_create_multi
    def create(self, vals_list):
        guard_create(vals_list)
        return super().create(vals_list)

    def unlink(self):
        if any(c.state != 'draft' for c in self):
            raise UserError('No se elimina un contrato confirmado.')
        return super().unlink()
