import sqlite3

import maxfi_schema


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    maxfi_schema.ensure_maxfi_tables(conn)
    return conn


def table_columns(conn, table):
    return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})")}


def test_ensure_maxfi_tables_returns_unchanged_status_dict():
    conn = make_db()
    status = maxfi_schema.ensure_maxfi_tables(conn)
    assert set(status.keys()) == {"unique_index_ready", "notes_column_ready"}
    assert status["unique_index_ready"] is True
    assert status["notes_column_ready"] is True


def test_maxfi_ledger_events_created_with_expected_columns():
    conn = make_db()
    columns = table_columns(conn, "maxfi_ledger_events")
    expected = {
        "id", "chain", "contract_address", "vault", "npm", "token_id",
        "pool_address", "event_type", "block_number", "block_timestamp",
        "tx_hash", "log_index", "topic0", "topics_json", "data_hex",
        "decoded_json", "created_at",
    }
    assert set(columns.keys()) == expected

    not_null = {name for name, row in columns.items() if row[3] == 1}
    assert not_null == {
        "chain", "contract_address", "event_type", "block_number",
        "block_timestamp", "tx_hash", "log_index", "topic0",
        "topics_json", "data_hex", "decoded_json", "created_at",
    }
    # vault/npm/token_id/pool_address are nullable - constraints 7/9
    assert "vault" not in not_null
    assert "npm" not in not_null
    assert "token_id" not in not_null
    assert "pool_address" not in not_null


def test_maxfi_ledger_events_unique_index_on_identity():
    conn = make_db()
    row = dict(
        chain="base", contract_address="0xabc", vault=None, npm=None,
        token_id=None, pool_address=None, event_type="Swap",
        block_number=1, block_timestamp="2026-01-01T00:00:00.000000Z",
        tx_hash="0xdeadbeef", log_index=0, topic0="0xtopic",
        topics_json="[]", data_hex="0x", decoded_json="{}",
        created_at="2026-01-01T00:00:00.000000Z",
    )
    conn.execute(
        """
        INSERT INTO maxfi_ledger_events
        (chain, contract_address, vault, npm, token_id, pool_address,
         event_type, block_number, block_timestamp, tx_hash, log_index,
         topic0, topics_json, data_hex, decoded_json, created_at)
        VALUES (:chain, :contract_address, :vault, :npm, :token_id,
                :pool_address, :event_type, :block_number,
                :block_timestamp, :tx_hash, :log_index, :topic0,
                :topics_json, :data_hex, :decoded_json, :created_at)
        """,
        row,
    )
    conn.commit()
    try:
        conn.execute(
            """
            INSERT INTO maxfi_ledger_events
            (chain, contract_address, vault, npm, token_id, pool_address,
             event_type, block_number, block_timestamp, tx_hash, log_index,
             topic0, topics_json, data_hex, decoded_json, created_at)
            VALUES (:chain, :contract_address, :vault, :npm, :token_id,
                    :pool_address, :event_type, :block_number,
                    :block_timestamp, :tx_hash, :log_index, :topic0,
                    :topics_json, :data_hex, :decoded_json, :created_at)
            """,
            row,
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised, "duplicate (chain, tx_hash, log_index) must violate the unique index"


def test_maxfi_ledger_positions_created_with_expected_columns_and_pk():
    conn = make_db()
    columns = table_columns(conn, "maxfi_ledger_positions")
    expected = {
        "chain", "vault", "npm", "token_id", "pool_id", "pool_address",
        "owner", "opened_at", "opened_block", "rebalanced_from_token_id",
        "rebalanced_to_token_id", "rebalanced_at", "rebalanced_block",
        "closed_at", "closed_block", "exit_amount0_wei", "exit_amount1_wei",
        "exit_net_fee0_wei", "exit_net_fee1_wei", "exit_price_usd",
        "exit_price_source", "claimed_gross0_wei", "claimed_gross1_wei",
        "claimed_net0_wei", "claimed_net1_wei", "compounded0_wei",
        "compounded1_wei", "basis_liquidity_wei", "basis_amount0_wei",
        "basis_amount1_wei", "basis_block", "basis_at", "basis_price_usd",
        "basis_price_source", "source_event_ids", "computed_at",
    }
    assert set(columns.keys()) == expected

    pk_columns = {name for name, row in columns.items() if row[5] > 0}
    assert pk_columns == {"chain", "vault", "npm", "token_id"}

    # basis_* and npm are nullable - constraints 8/9
    not_null = {name for name, row in columns.items() if row[3] == 1}
    for basis_col in (
        "basis_liquidity_wei", "basis_amount0_wei", "basis_amount1_wei",
        "basis_block", "basis_at", "basis_price_usd", "basis_price_source",
    ):
        assert basis_col not in not_null
    assert "npm" not in not_null
    assert "computed_at" in not_null


def test_ensure_maxfi_tables_idempotent_for_ledger_tables():
    conn = make_db()
    status_again = maxfi_schema.ensure_maxfi_tables(conn)
    assert status_again["unique_index_ready"] is True
    columns = table_columns(conn, "maxfi_ledger_events")
    assert "decoded_json" in columns
    columns2 = table_columns(conn, "maxfi_ledger_positions")
    assert "computed_at" in columns2


def test_maxfi_claims_initial_value_positions_untouched():
    conn = make_db()
    claims_columns = set(table_columns(conn, "maxfi_claims").keys())
    initial_value_columns = set(table_columns(conn, "maxfi_initial_value").keys())
    positions_columns = set(table_columns(conn, "maxfi_positions").keys())
    assert "notes" in positions_columns  # sanity: existing migrations still ran
    assert not any(c.startswith("ledger_") for c in claims_columns)
    assert not any(c.startswith("ledger_") for c in initial_value_columns)
    assert not any(c.startswith("ledger_") for c in positions_columns)
