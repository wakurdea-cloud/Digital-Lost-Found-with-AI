
import mysql.connector
import os

def get_connection():
    host = os.getenv("MYSQL_HOST", "localhost")

    config = {
        "host": host,
        "port": int(os.getenv("MYSQL_PORT", 3306)),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", "system"),
        "database": os.getenv("MYSQL_DB", "lost_found_ai")
    }

    if host != "localhost":
        config["ssl_disabled"] = False
        config["ssl_verify_cert"] = False

    return mysql.connector.connect(**config)
