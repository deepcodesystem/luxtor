# -*- coding: utf-8 -*-
from . import models
from . import wizards
from . import controllers


def post_init_hook(env):
    """Ensure the Services checkout step exists for all existing websites."""
    websites = env['website'].sudo().search([])
    websites._lx_ensure_services_step()
