-- Отдельная база под тесты: pytest делает TRUNCATE между кейсами,
-- и делать это в рабочей базе разработчика нельзя.
CREATE DATABASE wallet_test OWNER wallet;
