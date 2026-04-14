"""Shared voluptuous validators for the EnOcean (New) integration."""

from __future__ import annotations

import voluptuous as vol

import homeassistant.helpers.config_validation as cv

#: A 4-byte EnOcean device ID, each byte coerced into 0..255.
ENOCEAN_ID = vol.All(
    cv.ensure_list,
    vol.Length(min=4, max=4, msg="EnOcean IDs must be exactly 4 bytes"),
    [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))],
)
