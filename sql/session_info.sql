CREATE TABLE IF NOT EXISTS info (
    'session_id' VARCHAR(100) PRIMARY KEY,
    'session_name' VARCHAR(100),
    'date_created' VARCHAR(100),
    'date_last_commit' VARCHAR(100),
    'user_id' INTEGER
);