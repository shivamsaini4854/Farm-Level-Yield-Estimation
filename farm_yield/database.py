"""MySQL persistence; importing this module never connects to a database."""

from contextlib import contextmanager
import hashlib
import json
import logging
import os

import certifi
from dotenv import load_dotenv
import mysql.connector

from farm_yield.paths import CERTIFICATE, ENV_FILE

load_dotenv(ENV_FILE)
logger = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    pass


@contextmanager
def connection():
    required = ('DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME')
    if not all(os.getenv(key) for key in required):
        raise DatabaseUnavailable('Database configuration is incomplete.')
    conn = None
    try:
        conn = mysql.connector.connect(
            host=os.environ['DB_HOST'], user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'], database=os.environ['DB_NAME'],
            port=int(os.getenv('DB_PORT', '3306')), connection_timeout=5,
            ssl_ca=str(CERTIFICATE if CERTIFICATE.exists() else certifi.where()),
            ssl_verify_cert=True, ssl_verify_identity=True,
        )
        yield conn
    except mysql.connector.Error as exc:
        if conn is not None:
            conn.rollback()
        logger.error('Database operation failed (%s)', type(exc).__name__)
        raise DatabaseUnavailable('Database operation failed.') from exc
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def initialize_schema():
    statements = (
        """CREATE TABLE IF NOT EXISTS Predictions (
            prediction_id VARCHAR(36) PRIMARY KEY,
            session_hash CHAR(64) NOT NULL,
            payload JSON NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX session_history (session_hash, created_at)
        )""",
        """CREATE TABLE IF NOT EXISTS SeasonalObservations (
            record_id CHAR(64) PRIMARY KEY,
            dataset_version VARCHAR(64) NOT NULL,
            payload JSON NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    )
    with connection() as conn:
        with conn.cursor() as cursor:
            for sql in statements:
                cursor.execute(sql)
        conn.commit()


def check_ready():
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT 1 FROM Predictions LIMIT 1')
            cursor.fetchall()
    return True


def session_hash(session_id):
    return hashlib.sha256(session_id.encode()).hexdigest()


def save_prediction(session_id, payload):
    encoded = json.dumps(payload, allow_nan=False)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('INSERT INTO Predictions (prediction_id, session_hash, payload) VALUES (%s, %s, %s)',
                           (payload['prediction_id'], session_hash(session_id), encoded))
        conn.commit()


def prediction_history(session_id):
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT payload FROM Predictions WHERE session_hash = %s ORDER BY created_at DESC, prediction_id DESC LIMIT 20',
                           (session_hash(session_id),))
            rows = cursor.fetchall()
    return [json.loads(row[0]) for row in rows]


def ingest_observations(dataset_version, records):
    rows = []
    for record in records:
        encoded = json.dumps(record, sort_keys=True, allow_nan=False)
        identifier = hashlib.sha256((dataset_version + '\n' + encoded).encode()).hexdigest()
        rows.append((identifier, dataset_version, encoded))
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany('INSERT INTO SeasonalObservations (record_id, dataset_version, payload) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE record_id = record_id', rows)
            inserted = cursor.rowcount
        conn.commit()
    return inserted


if __name__ == '__main__':
    initialize_schema()
    print('PASS: prediction and observation tables created or already present.')
