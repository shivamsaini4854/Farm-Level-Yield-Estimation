from datagovindia import DataGovIndia

# Initialize with your key
API_KEY = "579b464db66ec23bdd000001f540892bf7114ade62cb5da2ee7efc11"
datagovin = DataGovIndia(API_KEY)

print("Starting manual sync (this may take 2-3 minutes)...")
# njobs=1 prevents the 'RLock' multiprocessing error on Windows
datagovin.sync_metadata(njobs=1) 
print("✓ Metadata Sync Complete!")