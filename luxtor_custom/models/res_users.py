# -*- coding: utf-8 -*-
import logging
import secrets

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_WELCOME_PROGRAM_NAME = 'WELCOME'
_PARAM_PCT_PRIMARY = 'luxtor.lx_welcome_reward_pct'
_PARAM_PCT_FALLBACK = 'luxtor.lx_new_customer_pct'
_DEFAULT_PCT = 5


# ── module-level helpers ───────────────────────────────────────────────────────

def _lx_get_welcome_pct(env):
    """Return the configured welcome discount % as a positive integer (default 5)."""
    icp = env['ir.config_parameter'].sudo()
    for param in (_PARAM_PCT_PRIMARY, _PARAM_PCT_FALLBACK):
        raw = icp.get_param(param)
        if raw:
            try:
                v = int(float(raw))
                if v > 0:
                    return v
            except (ValueError, TypeError):
                pass
    return _DEFAULT_PCT


def _lx_find_welcome_program(env):
    """Return the active WELCOME loyalty.program, or an empty recordset."""
    try:
        return env['loyalty.program'].sudo().search(
            [('name', '=ilike', _WELCOME_PROGRAM_NAME), ('active', '=', True)],
            limit=1,
        )
    except Exception:
        _logger.exception('WELCOME-COUPON: could not query loyalty.program')
        return env['loyalty.program'].sudo().browse()


def _lx_generate_coupon_code(env, prefix='WELCOME'):
    """Generate a unique coupon code not yet present in loyalty.card."""
    LoyaltyCard = env['loyalty.card'].sudo()
    for _ in range(10):
        code = '%s-%s' % (prefix, secrets.token_hex(3).upper())
        if not LoyaltyCard.search([('code', '=', code)], limit=1):
            return code
    # Extremely unlikely collision path — use longer token
    return '%s-%s' % (prefix, secrets.token_hex(6).upper())


# ── model extension ────────────────────────────────────────────────────────────

class ResUsers(models.Model):
    _inherit = 'res.users'

    # ── public read API ────────────────────────────────────────────────────────

    def _lx_get_welcome_coupon_display_data(self, order=False, send_email=False):
        """Return a display-data dict consumed by portal controller and cart template.

        Keys: code, pct, pct_label, is_available, show_coupon, applied, coupon.
        Never raises — returns a zero-state dict on any error.
        """
        _empty = dict(
            code=False, pct=0, pct_label='0',
            is_available=False, show_coupon=False,
            applied=False, coupon=False,
        )
        try:
            self.ensure_one()
            partner = self.sudo().partner_id
            if not partner or not partner.id:
                return _empty

            pct = _lx_get_welcome_pct(self.env)
            coupon = self.sudo()._lx_ensure_welcome_coupon(
                pct=pct, send_email=send_email
            )
            if not coupon:
                return _empty

            code = coupon.code or False

            # A card with points <= 0 has been fully consumed in a previous order.
            points_remaining = float(getattr(coupon, 'points', 1) or 1)
            applied = points_remaining <= 0

            # Also check the current order's discount lines (in-cart detection).
            if not applied and order and hasattr(order, '_lx_has_welcome_coupon_applied'):
                applied = bool(order._lx_has_welcome_coupon_applied(coupon=coupon))

            is_available = bool(code) and not applied
            return dict(
                code=code,
                pct=pct,
                pct_label=str(pct),
                is_available=is_available,
                show_coupon=is_available,
                applied=applied,
                coupon=coupon,
            )
        except Exception:
            _logger.exception(
                'WELCOME-COUPON: _lx_get_welcome_coupon_display_data failed (user %s)',
                self.id if self else '?',
            )
            return _empty

    # ── idempotent coupon creation ─────────────────────────────────────────────

    def _lx_ensure_welcome_coupon(self, pct=None, send_email=True):
        """Find or create the welcome loyalty.card for this user's partner.

        Idempotent — safe to call multiple times; creates at most one card.
        Returns the loyalty.card record, or False on any error / missing program.
        """
        try:
            self.ensure_one()
            partner = self.sudo().partner_id
            if not partner or not partner.id:
                return False

            program = _lx_find_welcome_program(self.env)
            if not program:
                _logger.warning(
                    'WELCOME-COUPON: No active loyalty program named "%s" — '
                    'skipping coupon for partner %s.',
                    _WELCOME_PROGRAM_NAME, partner.id,
                )
                return False

            # Idempotency: find any existing card for this partner+program.
            existing = self.env['loyalty.card'].sudo().search([
                ('program_id', '=', program.id),
                ('partner_id', '=', partner.id),
            ], limit=1)
            if existing:
                if send_email and not partner.sudo().lx_welcome_coupon_mail_sent:
                    self.sudo()._lx_send_welcome_coupon_email(
                        partner=partner,
                        coupon=existing,
                        pct=pct if pct is not None else _lx_get_welcome_pct(self.env),
                    )
                return existing

            if pct is None:
                pct = _lx_get_welcome_pct(self.env)

            code = _lx_generate_coupon_code(self.env)
            card = self.env['loyalty.card'].sudo().create({
                'program_id': program.id,
                'partner_id': partner.id,
                'code': code,
                'points': 1,
            })

            partner.sudo().write({
                'lx_welcome_coupon_code': code,
            })

            _logger.info(
                'WELCOME-COUPON: Created card %s (%s%%) for partner %s (user %s)',
                code, pct, partner.id, self.id,
            )

            if send_email:
                self.sudo()._lx_send_welcome_coupon_email(
                    partner=partner, coupon=card, pct=pct
                )
            return card

        except Exception:
            _logger.exception(
                'WELCOME-COUPON: _lx_ensure_welcome_coupon failed (user %s)',
                self.id if self else '?',
            )
            return False

    # ── one-shot email send ────────────────────────────────────────────────────

    def _lx_send_welcome_coupon_email(self, partner, coupon, pct):
        """Send the welcome-coupon email exactly once (guarded by lx_welcome_coupon_mail_sent)."""
        try:
            if partner.sudo().lx_welcome_coupon_mail_sent:
                return

            if not partner.email:
                _logger.warning(
                    'WELCOME-COUPON: partner %s has no email — skipping welcome email.',
                    partner.id,
                )
                return

            template = self.env.ref(
                'luxtor_custom.mail_template_welcome_coupon',
                raise_if_not_found=False,
            )
            if not template:
                _logger.warning(
                    'WELCOME-COUPON: mail_template_welcome_coupon not found — '
                    'email not sent for partner %s.', partner.id,
                )
                return

            template.sudo().with_context(
                coupon_code=coupon.code or '',
                coupon_value=pct,
            ).send_mail(partner.id, force_send=True, raise_exception=False)

            partner.sudo().write({
                'lx_welcome_coupon_mail_sent': True,
                'lx_welcome_coupon_mail_sent_date': fields.Datetime.now(),
                'lx_welcome_coupon_mail_sent_to': partner.email,
            })

            _logger.info(
                'WELCOME-COUPON: Email sent to %s (partner %s)',
                partner.email, partner.id,
            )
        except Exception:
            _logger.exception(
                'WELCOME-COUPON: _lx_send_welcome_coupon_email failed (partner %s)',
                partner.id if partner else '?',
            )

    # Auto-assign intentionally omitted from create() to avoid writes to
    # res.partner / loyalty.card inside the res.users transaction.
    # Coupon is created lazily: first time a portal user visits /my,
    # _prepare_portal_layout_values calls this method with send_email=True.
