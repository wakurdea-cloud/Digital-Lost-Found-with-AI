import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="system",   
        database="lost_found_ai"
    )
    
