import pandas as pd
from datagovindia import DataGovIndia

def main():
    datagovin = DataGovIndia()
    resource_id = "3ba2a033-dc1e-451e-8a71-872f2d9c6c59" 

    try:
        print("Downloading full dataset for local extraction...")
        df = datagovin.get_data(resource_id)
        
        # 1. Clean column names (strip spaces and uppercase)
        df.columns = [str(col).strip().upper() for col in df.columns]
        print(f"Columns Found: {df.columns.tolist()}")

        # 2. Find the correct State/District columns dynamically
        state_col = next((c for c in df.columns if 'STATE' in c), None)
        dist_col = next((c for c in df.columns if 'DISTRICT' in c), None)

        if state_col and dist_col:
            # 3. Flexible filtering (case-insensitive)
            saharanpur_df = df[
                (df[state_col].astype(str).str.contains('UTTAR', case=False, na=False)) & 
                (df[dist_col].astype(str).str.contains('SAHARANPUR', case=False, na=False))
            ]
            
            if not saharanpur_df.empty:
                saharanpur_df.to_csv("saharanpur_yield_history.csv", index=False)
                print(f"✓ DONE! Saved {len(saharanpur_df)} records for Saharanpur.")
                print(saharanpur_df[['CROP', 'CROP_YEAR', 'PRODUCTION']].head())
            else:
                # If still 0, let's see what the states are actually called
                print("✗ No Saharanpur found. Actual States in data:", df[state_col].unique()[:5])
        else:
            print("✗ Could not find State or District columns.")

    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == '__main__':
    main()