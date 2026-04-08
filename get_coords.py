import mysql.connector

try:
    db = mysql.connector.connect(
        host="localhost",
        user="root",          
        password="12231691223178", # Use the password that just worked!
        database="FarmYieldSystem"
    )
    
    cursor = db.cursor(dictionary=True)
    
    # We remove the WHERE clause completely. 
    # This just grabs the first row in the table.
    cursor.execute("SELECT * FROM Farmers LIMIT 1")
    farmer = cursor.fetchone()
    
    if farmer:
        print("\n--- FIRST FARMER RECORD FOUND ---")
        for column_name, value in farmer.items():
            print(f"{column_name}: {value}")
        print("---------------------------------\n")
    else:
        print("The Farmers table is completely empty!")
    
except mysql.connector.Error as err:
    print(f"Database Error: {err}")