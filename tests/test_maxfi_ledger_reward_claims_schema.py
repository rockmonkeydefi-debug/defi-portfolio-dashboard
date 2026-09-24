"""Emissions C1 - schema-only tests for maxfi_ledger_reward_claims
(tests/test_maxfi_ledger_schema.py pattern). No reader or writer exists
yet: the table exists with exactly the declared columns, nullability and
PK, rejects a NULL in any key column, keeps one row per (chain, tx_hash,
token_id, reward_token), and ensure_maxfi_tables stays idempotent with its
return dict unchanged."""
import sqlite3

import maxfi_schema

PK = ("chain", "tx_hash", "token_id", "reward_token")


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def table_columns(conn, table):
    return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")}


def _row(**overrides):
    row = dict(
        chain="base", tx_hash="0xabc", token_id="67658300",
        reward_token="0x940181a94a35a4569e4529a3cdfb74e38fd98631",
        log_index=1, block_number=2, block_timestamp="2026-04-22T13:24:37+00:00",
        fee_wei="0", treasury_wei="0", referral_wei="0",
        verification_status="verified", computed_at="2026-09-24T00:00:00+00:00",
    )
    row.update(overrides)
    return row


def _insert(conn, row):
    cols = ", ".join(row)
    conn.execute(
        f"INSERT INTO maxfi_ledger_reward_claims ({cols}) VALUES ({', '.join(':' + c for c in row)})",
        row,
    )


def test_reward_claims_columns_nullability_and_pk():
    conn = make_db()
    columns = table_columns(conn, "maxfi_ledger_reward_claims")
    assert set(columns) == {
        "chain", "tx_hash", "token_id", "reward_token", "vault", "npm",
        "log_index", "block_number", "block_timestamp",
        "gross_wei", "fee_wei", "treasury_wei", "referral_wei", "net_wei",
        "claim_path", "gross_source",
        "transfer_log_index", "transfer_to", "transfer_wei", "verification_status",
        "owner", "net_usd", "price_source", "price_block", "computed_at",
    }
    not_null = {name for name, row in columns.items() if row[3] == 1}
    assert not_null == {
        "chain", "tx_hash", "token_id", "reward_token", "log_index", "block_number",
        "block_timestamp", "fee_wei", "treasury_wei", "referral_wei",
        "verification_status", "computed_at",
    }
    pk = sorted((row[5], name) for name, row in columns.items() if row[5] > 0)
    assert tuple(name for _, name in pk) == PK
    # wei amounts are decimal TEXT, never INTEGER/REAL (totals exceed 2^53)
    for col in ("gross_wei", "fee_wei", "treasury_wei", "referral_wei", "net_wei", "transfer_wei"):
        assert columns[col][2] == "TEXT", col


def test_reward_claims_pk_rejects_null_in_every_key_column():
    conn = make_db()
    for col in PK:
        try:
            _insert(conn, _row(**{col: None}))
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised, f"NULL {col} must violate NOT NULL"
    assert conn.execute("SELECT COUNT(*) FROM maxfi_ledger_reward_claims").fetchone()[0] == 0


def test_reward_claims_one_row_per_key_reward_token_distinguishes():
    conn = make_db()
    _insert(conn, _row())
    # a fee key with no claim: gross/net/path/source are nullable
    _insert(conn, _row(reward_token="0x3055913c90fcc1a6ce9a358911721eeb942013a1",
                       verification_status="fee_without_claim"))
    conn.commit()
    try:
        _insert(conn, _row(gross_wei="1"))
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "duplicate (chain, tx_hash, token_id, reward_token) must violate the PK"
    assert conn.execute("SELECT COUNT(*) FROM maxfi_ledger_reward_claims").fetchone()[0] == 2


def test_reward_claims_idempotent_status_dict_and_claims_table_untouched():
    conn = make_db()
    _insert(conn, _row())
    conn.commit()
    status = maxfi_schema.ensure_maxfi_tables(conn)
    assert set(status) == {"unique_index_ready", "notes_column_ready"}
    assert conn.execute("SELECT COUNT(*) FROM maxfi_ledger_reward_claims").fetchone()[0] == 1
    claims_pk = sorted((row[5], name) for name, row in table_columns(conn, "maxfi_ledger_claims").items()
                       if row[5] > 0)
    assert tuple(name for _, name in claims_pk) == ("chain", "tx_hash", "token_id")
    assert "reward_token" not in table_columns(conn, "maxfi_ledger_claims")
