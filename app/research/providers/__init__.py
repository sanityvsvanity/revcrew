"""Provider adapters, one module per tier.

Every function returns a plain ``dict`` with at least ``status`` (``ok``, ``empty``, ``blocked`` or
``error``), ``provider``, ``credits`` and ``latency_ms``. The router records that dict as a ledger row.
Adapters do not raise on a provider failure; they return ``status="error"`` with the message so the
waterfall can fall through and the ledger keeps the miss.
"""
