import os
import unittest
from unittest.mock import MagicMock, patch

import mysql.connector

from farm_yield import database


class DatabaseTests(unittest.TestCase):
    def test_partial_ingestion_rolls_back_on_driver_error(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.executemany.side_effect = mysql.connector.Error('forced insert failure')
        env = {'DB_HOST': 'localhost', 'DB_USER': 'test', 'DB_PASSWORD': 'db-' + 'fixture', 'DB_NAME': 'test'}
        with patch.dict(os.environ, env, clear=True), patch.object(database.mysql.connector, 'connect', return_value=conn):
            with self.assertRaises(database.DatabaseUnavailable):
                database.ingest_observations('v1', [{'month': '2016-01-01'}])
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_history_query_is_scoped_and_parameterized(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [('{"prediction_id":"own"}',)]
        env = {'DB_HOST': 'localhost', 'DB_USER': 'test', 'DB_PASSWORD': 'db-' + 'fixture', 'DB_NAME': 'test'}
        with patch.dict(os.environ, env, clear=True), patch.object(database.mysql.connector, 'connect', return_value=conn):
            self.assertEqual(database.prediction_history('visitor')[0]['prediction_id'], 'own')
        sql, values = cursor.execute.call_args.args
        self.assertIn('WHERE session_hash = %s', sql)
        self.assertEqual(values, (database.session_hash('visitor'),))


if __name__ == '__main__':
    unittest.main()
