import base64
from datetime import date

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.addons.biotex_base.models.integrity import transition


@tagged('post_install', '-at_install')
class TestContractActivation(TransactionCase):
    """Activation requirements must be editable and identify actual omissions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Prueba de activación de contrato',
            'biotex_partner_type': 'institution',
        })

    def setUp(self):
        super().setUp()
        year = date.today().year
        values = {
            'name': 'TEST-ACTIVATION-REQUIREMENTS',
            'partner_id': self.partner.id,
            'date_start': date(year, 1, 1),
            'date_end': date(year, 12, 31),
            'external_ref': 'TEST-EVENT-001',
            'amount_contract': 100,
        }
        if 'lifecycle_enabled' in self.env['biotex.contract']._fields:
            # Satisfy the optional extension so each test isolates its intended
            # missing base requirement without bypassing institutional checks.
            values.update(control_mode='amount', award_scope='open_amount',
                          scope_source='Synthetic amount-only contract for activation tests')
        self.contract = self.env['biotex.contract'].create(values)
        attachment = self.env['ir.attachment'].create({
            'name': 'test-activation.txt',
            'datas': base64.b64encode(b'Automated test fixture; rolls back.'),
            'res_model': self.contract._name,
            'res_id': self.contract.id,
            'mimetype': 'text/plain',
        })
        self.contract.document_ids = attachment

    def test_form_exposes_folio_and_documents(self):
        view = self.contract.get_view(
            view_id=self.env.ref('biotex_contract.view_contract_form').id,
            view_type='form',
        )
        arch = etree.fromstring(view['arch'])
        folio = arch.xpath("//field[@name='external_ref']")
        self.assertEqual(len(folio), 1)
        self.assertFalse(folio[0].get('invisible'))
        self.assertFalse(folio[0].get('readonly'))
        self.assertTrue(arch.xpath("//page[@name='docs']//field[@name='document_ids']"))

    def test_only_missing_folio_is_reported(self):
        self.contract.external_ref = False
        with self.assertRaises(UserError) as raised:
            self.contract.action_activate()
        self.assertEqual(str(raised.exception), 'Para activar el contrato, complete:\n- Folio externo / evento')
        self.assertEqual(self.contract.state, 'draft')

    def test_only_missing_document_is_reported(self):
        self.contract.document_ids = False
        with self.assertRaises(UserError) as raised:
            self.contract.action_activate()
        message = str(raised.exception)
        self.assertIn('Documentos (contrato, fallo, anexos)', message)
        self.assertIn('pestaña Documentos y notas', message)
        self.assertNotIn('vigencia', message)
        self.assertNotIn('Folio externo', message)
        self.assertEqual(self.contract.state, 'draft')

    def test_missing_dates_are_reported_individually(self):
        for field, label in [('date_start', 'Inicio de vigencia'), ('date_end', 'Fin de vigencia')]:
            with self.subTest(field=field):
                previous = self.contract[field]
                self.contract[field] = False
                with self.assertRaisesRegex(UserError, label):
                    self.contract.action_activate()
                self.contract[field] = previous

    def test_reports_all_missing_requirements(self):
        self.contract.write({'date_start': False, 'date_end': False, 'external_ref': False, 'document_ids': False})
        with self.assertRaises(UserError) as raised:
            self.contract.action_activate()
        message = str(raised.exception)
        for label in ('Inicio de vigencia', 'Fin de vigencia', 'Folio externo / evento', 'Documentos (contrato, fallo, anexos)'):
            self.assertIn(label, message)

    def test_whitespace_is_not_a_folio(self):
        self.contract.external_ref = '   '
        with self.assertRaisesRegex(UserError, 'Folio externo / evento'):
            self.contract.action_activate()

    def test_valid_activation_is_idempotent(self):
        self.assertTrue(self.contract.action_activate())
        self.assertEqual(self.contract.state, 'active')
        self.assertTrue(self.contract.action_activate())
        self.assertEqual(self.contract.state, 'active')

    def test_closed_contract_reports_state(self):
        transition(self.contract, {'state': 'closed'})
        with self.assertRaisesRegex(UserError, 'Solo se puede activar un contrato en borrador'):
            self.contract.action_activate()
        self.assertEqual(self.contract.state, 'closed')

    def test_amount_or_lines_still_required(self):
        if 'lifecycle_enabled' in self.contract._fields:
            # Simulate a pre-upgrade contract; ordinary create/write deliberately
            # cannot disable institutional controls for newly created contracts.
            transition(self.contract, {'lifecycle_enabled': False})
        self.contract.amount_contract = 0
        with self.assertRaisesRegex(UserError, 'Capture las claves o el monto del contrato'):
            self.contract.action_activate()
        self.assertEqual(self.contract.state, 'draft')

    def test_institutional_amount_still_required(self):
        if 'lifecycle_enabled' not in self.contract._fields:
            self.skipTest('Optional institutional lifecycle module is not installed')
        self.assertTrue(self.contract.lifecycle_enabled)
        self.contract.amount_contract = 0
        with self.assertRaisesRegex(UserError, 'modalidad y límites mínimo/máximo'):
            self.contract.action_activate()
        self.assertEqual(self.contract.state, 'draft')
