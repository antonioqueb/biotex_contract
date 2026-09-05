import math
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.biotex_base.models.integrity import guard_create, guard_write, lock_records, require_group, transition


class Amendment(models.Model):
    _name = 'biotex.contract.amendment'
    _description = 'Modificación contractual documentada'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    contract_id = fields.Many2one('biotex.contract', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    name = fields.Char(string='Documento / folio', required=True, tracking=True)
    date_approved = fields.Date(string='Fecha del documento', required=True)
    date_effective = fields.Date(string='Vigente desde', required=True)
    date_end = fields.Date(string='Nuevo fin de vigencia')
    amount_delta = fields.Monetary(string='Cambio de monto (+ / −)', tracking=True)
    before_amount = fields.Monetary(readonly=True, copy=False)
    after_amount = fields.Monetary(readonly=True, copy=False)
    state = fields.Selection([('draft', 'Borrador'), ('approved', 'Aprobada'), ('cancelled', 'Cancelada')], default='draft', tracking=True, copy=False)
    transition_notes = fields.Text(string='Condiciones y transición', required=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Documento original')
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        guard_create(vals_list, ('approved_by_id', 'before_amount', 'after_amount'))
        return super().create(vals_list)

    def write(self, vals):
        guard_write(self, vals, ('state', 'approved_by_id', 'before_amount', 'after_amount'),
                    ('contract_id', 'name', 'date_approved', 'date_effective', 'date_end', 'amount_delta', 'transition_notes', 'attachment_ids'))
        return super().write(vals)

    def action_approve(self):
        require_group(self, 'biotex_base.group_biotex_direction')
        lock_records(self.contract_id)
        lock_records(self)
        for rec in self:
            if rec.state == 'approved':
                continue
            if rec.state != 'draft' or not rec.attachment_ids or rec.contract_id.state == 'draft':
                raise UserError('Se requiere contrato confirmado y documento modificatorio original.')
            if rec.date_effective > fields.Date.context_today(rec):
                raise UserError('La modificación se conserva pendiente hasta su vigencia; aún no aumenta el saldo.')
            if not math.isfinite(rec.amount_delta):
                raise ValidationError('El cambio de monto debe ser finito.')
            before = rec.contract_id.amount_total
            if before + rec.amount_delta < 0:
                raise ValidationError('El monto vigente no puede ser negativo.')
            transition(rec, {'state': 'approved', 'approved_by_id': self.env.uid,
                             'before_amount': before, 'after_amount': before + rec.amount_delta})
            if rec.contract_id.amount_applied > rec.after_amount:
                rec.contract_id.activity_schedule('mail.mail_activity_data_todo',
                    user_id=rec.contract_id.responsible_id.id or self.env.uid,
                    summary='Modificación reduce el contrato por debajo de lo aplicado: resolver diferencia')
        return True

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError('La modificación aprobada se conserva; registre otra corrección documentada.')
        return super().unlink()
