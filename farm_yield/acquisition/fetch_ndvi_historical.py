"""
fetch_ndvi_historical.py
=========================
Fetches historical MODIS NDVI for 276 districts across 5 states (UP, MP,
Karnataka, Bihar, Maharashtra) for years 1997-2019.

KEY OPTIMIZATION: Instead of 1 GEE call per district per year (5,166 calls),
this script fetches ALL districts in ONE call per year using a FeatureCollection.
Total calls = 20 years = ~20 calls. Estimated time: 5-15 minutes.

MODIS product: MOD13A3 v061
- Monthly NDVI composites, 1km resolution
- Covers 2000-present (MODIS launched 1999, data from 2000)
- Note: APY has data from 1997, but MODIS starts 2000.
  Years 1997-1999 will have no NDVI (left as NaN, handled in training).

Season slicing (done in pandas, zero extra API calls):
  - Kharif    : Jun-Nov (months 6-11)
  - Rabi      : Oct-Mar (months 10-12 of year Y, 1-3 of year Y+1)
  - Whole Year: Jan-Dec (months 1-12)
  - Summer    : Mar-Jun (months 3-6)

Usage:
    python fetch_ndvi_historical.py

    To fetch a specific state only (useful for splitting across multiple runs):
    python fetch_ndvi_historical.py --state "Uttar Pradesh"

    To merge multiple state output files into one:
    python fetch_ndvi_historical.py --merge

Output:
    ndvi_historical_<state>.csv   per-state file (safe to run in parallel)
    ndvi_historical_all.csv       merged all-India file (after --merge)
"""

from farm_yield.paths import RAW_DATA, NDVI_RAW, PROCESSED_DATA

import ee
import pandas as pd
import numpy as np
import json
import os
import time
import argparse
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
GEE_PROJECT = 'madd-1eddf'
MODIS_COLLECTION = 'MODIS/061/MOD13A3'  # Monthly NDVI, 1km
NDVI_BAND = 'NDVI'
NDVI_SCALE_FACTOR = 0.0001  # MODIS NDVI is stored as int, multiply by 0.0001
MODIS_START_YEAR = 2000     # MODIS data starts from 2000
APY_END_YEAR = 2019

TARGET_STATES = [
    'Uttar Pradesh', 'Madhya Pradesh', 'Karnataka', 'Bihar', 'Maharashtra'
]

# ── DISTRICT COORDINATES ─────────────────────────────────────────────────────
DISTRICT_COORDS = {
    # UTTAR PRADESH
    "AGRA": (27.1767, 78.0081), "ALIGARH": (27.8974, 78.0880),
    "ALLAHABAD": (25.4358, 81.8463), "ALMORA": (29.5971, 79.6591),
    "AMBEDKAR NAGAR": (26.3990, 82.5437), "AMETHI": (26.1620, 81.7370),
    "AMROHA": (28.9042, 78.4678), "AURAIYA": (26.4605, 79.5175),
    "AZAMGARH": (26.0672, 83.1844), "BAGESHWAR": (29.8370, 79.7714),
    "BAGHPAT": (28.9433, 77.2166), "BAHRAICH": (27.5747, 81.5964),
    "BALLIA": (25.7557, 84.1465), "BALRAMPUR": (27.4312, 82.1834),
    "BANDA": (25.4800, 80.3330), "BARABANKI": (26.9342, 81.1855),
    "BAREILLY": (28.3670, 79.4304), "BASTI": (26.7946, 82.7180),
    "BIJNOR": (29.3721, 78.1358), "BUDAUN": (28.0408, 79.1258),
    "BULANDSHAHR": (28.4069, 77.8497), "CHAMOLI": (30.4021, 79.3213),
    "CHAMPAWAT": (29.3350, 80.0908), "CHANDAULI": (25.2596, 83.2714),
    "CHITRAKOOT": (25.1906, 80.8960), "DEHRADUN": (30.3165, 78.0322),
    "DEORIA": (26.4979, 83.7880), "ETAH": (27.5580, 78.6717),
    "ETAWAH": (26.7853, 79.0191), "FAIZABAD": (26.7751, 82.1468),
    "FARRUKHABAD": (27.3874, 79.5827), "FATEHPUR": (25.9300, 80.8130),
    "FIROZABAD": (27.1592, 78.3957), "GAUTAM BUDDHA NAGAR": (28.5355, 77.3910),
    "GHAZIABAD": (28.6692, 77.4538), "GHAZIPUR": (25.5796, 83.5699),
    "GONDA": (27.1330, 81.9604), "GORAKHPUR": (26.7606, 83.3732),
    "HAMIRPUR": (25.9534, 80.1537), "HAPUR": (28.7301, 77.7757),
    "HARDOI": (27.3948, 80.1379), "HARIDWAR": (29.9457, 78.1642),
    "HATHRAS": (27.5958, 78.0522), "JALAUN": (26.1413, 79.3516),
    "JAUNPUR": (25.7463, 82.6844), "JHANSI": (25.4484, 78.5685),
    "KANNAUJ": (27.0553, 79.9148), "KANPUR DEHAT": (26.4025, 79.8208),
    "KANPUR NAGAR": (26.4499, 80.3319), "KASGANJ": (27.8081, 78.6447),
    "KAUSHAMBI": (25.5369, 81.3890), "KHERI": (27.9506, 80.7846),
    "KUSHI NAGAR": (26.7394, 83.8870), "LALITPUR": (24.6882, 78.4148),
    "LUCKNOW": (26.8467, 80.9462), "MAHARAJGANJ": (27.1303, 83.5608),
    "MAHOBA": (25.2891, 79.8735), "MAINPURI": (27.2258, 79.0078),
    "MATHURA": (27.4924, 77.6737), "MAU": (25.9440, 83.5615),
    "MEERUT": (28.9845, 77.7064), "MIRZAPUR": (25.1448, 82.5717),
    "MORADABAD": (28.8386, 78.7733), "MUZAFFARNAGAR": (29.4727, 77.7085),
    "NAINITAL": (29.3919, 79.4542), "PAURI GARHWAL": (29.6956, 78.9688),
    "PILIBHIT": (28.6317, 79.8057), "PITHORAGARH": (29.5826, 80.2180),
    "PRATAPGARH": (25.8996, 81.9935), "RAE BARELI": (26.2328, 81.2387),
    "RAMPUR": (28.8159, 79.0256), "RUDRA PRAYAG": (30.2847, 78.9808),
    "SAHARANPUR": (30.0289, 77.1462), "SAMBHAL": (28.5904, 78.5691),
    "SANT KABEER NAGAR": (26.7867, 83.0566), "SANT RAVIDAS NAGAR": (25.3863, 82.5672),
    "SHAHJAHANPUR": (27.8833, 79.9053), "SHAMLI": (29.4490, 77.3178),
    "SHRAVASTI": (27.5289, 81.9335), "SIDDHARTH NAGAR": (27.2800, 83.0681),
    "SITAPUR": (27.5632, 80.6840), "SONBHADRA": (24.6826, 83.0637),
    "SULTANPUR": (26.2613, 82.0723), "TEHRI GARHWAL": (30.3817, 78.4800),
    "UDAM SINGH NAGAR": (28.9995, 79.5185), "UNNAO": (26.5455, 80.4977),
    "UTTAR KASHI": (30.7268, 78.4354), "VARANASI": (25.3176, 82.9739),
    # MADHYA PRADESH
    "AGAR MALWA": (23.7121, 76.0177), "ALIRAJPUR": (22.3085, 74.3614),
    "ANUPPUR": (23.1031, 81.6904), "ASHOKNAGAR": (24.5741, 77.7285),
    "BALAGHAT": (21.8135, 80.1862), "BARWANI": (22.0330, 74.9021),
    "BASTAR": (19.1174, 81.9538), "BETUL": (21.9074, 77.9058),
    "BHIND": (26.5617, 78.7870), "BHOPAL": (23.2599, 77.4126),
    "BILASPUR": (22.0797, 82.1391), "BURHANPUR": (21.3041, 76.2279),
    "CHHATARPUR": (24.9176, 79.5857), "CHHINDWARA": (22.0574, 78.9382),
    "DAMOH": (23.8388, 79.4419), "DANTEWADA": (18.8956, 81.3473),
    "DATIA": (25.6677, 78.4636), "DEWAS": (22.9623, 76.0508),
    "DHAMTARI": (20.7060, 81.5482), "DHAR": (22.5990, 75.2999),
    "DINDORI": (22.9475, 81.0791), "DURG": (21.1900, 81.2849),
    "GUNA": (24.6479, 77.3161), "GWALIOR": (26.2183, 78.1828),
    "HARDA": (22.3393, 77.0922), "HOSHANGABAD": (22.7479, 77.7273),
    "INDORE": (22.7196, 75.8577), "JABALPUR": (23.1815, 79.9864),
    "JANJGIR-CHAMPA": (22.0108, 82.5687), "JASHPUR": (22.8862, 84.1356),
    "JHABUA": (22.7687, 74.5931), "KABIRDHAM": (22.0000, 81.2667),
    "KANKER": (20.2739, 81.4921), "KATNI": (23.8333, 80.4000),
    "KHANDWA": (21.8224, 76.3508), "KHARGONE": (21.8230, 75.6119),
    "KORBA": (22.3595, 82.7501), "KOREA": (23.3091, 82.7265),
    "MAHASAMUND": (21.1104, 82.0952), "MANDLA": (22.5984, 80.3730),
    "MANDSAUR": (24.0740, 75.0688), "MORENA": (26.4944, 77.9982),
    "NARSINGHPUR": (22.9496, 79.1944), "NEEMUCH": (24.4765, 74.8700),
    "NIWARI": (25.0000, 79.0000), "PANNA": (24.7180, 80.1856),
    "RAIPUR": (21.2514, 81.6296), "RAISEN": (23.3265, 77.7878),
    "RAJGARH": (23.9417, 76.6920), "RAJNANDGAON": (21.0972, 81.0320),
    "RATLAM": (23.3338, 75.0376), "REWA": (24.5362, 81.3037),
    "SAGAR": (23.8388, 78.7378), "SATNA": (24.5869, 80.8322),
    "SEHORE": (23.2017, 77.0849), "SEONI": (22.0876, 79.5373),
    "SHAHDOL": (23.2963, 81.3511), "SHAJAPUR": (23.4273, 76.2773),
    "SHEOPUR": (25.6584, 76.7031), "SHIVPURI": (25.4258, 77.6584),
    "SIDHI": (24.4160, 81.8799), "SINGRAULI": (24.1997, 82.6741),
    "SURGUJA": (23.1165, 83.1940), "TIKAMGARH": (24.7431, 78.8392),
    "UJJAIN": (23.1765, 75.7885), "UMARIA": (23.5240, 80.8378),
    "VIDISHA": (23.5252, 77.8098),
    # KARNATAKA
    "BAGALKOTE": (16.1800, 75.6960), "BALLARI": (15.1394, 76.9214),
    "BANGALORE RURAL": (13.2257, 77.5724), "BELAGAVI": (15.8497, 74.4977),
    "BENGALURU URBAN": (12.9716, 77.5946), "BIDAR": (17.9104, 77.5199),
    "CHAMARAJANAGARA": (11.9265, 76.9437), "CHIKKABALLAPURA": (13.4355, 77.7315),
    "CHIKKAMAGALURU": (13.3161, 75.7720), "CHITRADURGA": (14.2251, 76.3980),
    "DAKSHINA KANNADA": (12.8438, 75.2479), "DAVANGERE": (14.4644, 75.9218),
    "DHARWAD": (15.4589, 75.0078), "GADAG": (15.4317, 75.6355),
    "HASSAN": (13.0072, 76.1004), "HAVERI": (14.7957, 75.3996),
    "KALABURAGI": (17.3297, 76.8343), "KODAGU": (12.4200, 75.7382),
    "KOLAR": (13.1367, 78.1298), "KOPPAL": (15.3528, 76.1547),
    "MANDYA": (12.5218, 76.8951), "MYSURU": (12.2958, 76.6394),
    "RAICHUR": (16.2120, 77.3439), "RAMANAGARA": (12.7157, 77.2799),
    "SHIVAMOGGA": (13.9299, 75.5681), "TUMAKURU": (13.3392, 77.1011),
    "UDUPI": (13.3409, 74.7421), "UTTARA KANNADA": (14.7754, 74.7551),
    "VIJAYAPURA": (16.8302, 75.7100), "YADAGIRI": (16.7712, 77.1370),
    # BIHAR
    "ARARIA": (26.1479, 87.4710), "ARWAL": (25.2529, 84.6812),
    "AURANGABAD": (24.7518, 84.3741), "BANKA": (24.8800, 86.9200),
    "BEGUSARAI": (25.4182, 86.1272), "BHAGALPUR": (25.2425, 86.9842),
    "BHOJPUR": (25.5599, 84.5154), "BOKARO": (23.6693, 85.9915),
    "BUXAR": (25.5655, 83.9737), "CHATRA": (24.2120, 84.8760),
    "DARBHANGA": (26.1542, 85.8918), "DEOGHAR": (24.4853, 86.6952),
    "DHANBAD": (23.7957, 86.4304), "DUMKA": (24.2663, 87.2476),
    "EAST SINGHBUM": (22.8046, 86.2029), "GARHWA": (24.1695, 83.8118),
    "GAYA": (24.7955, 85.0002), "GIRIDIH": (24.1851, 86.3009),
    "GODDA": (24.8290, 87.2110), "GOPALGANJ": (26.4668, 84.4374),
    "GUMLA": (23.0430, 84.5416), "HAZARIBAGH": (23.9925, 85.3613),
    "JAMUI": (24.9270, 86.2240), "JEHANABAD": (25.2061, 84.9879),
    "KAIMUR (BHABUA)": (25.0437, 83.5988), "KATIHAR": (25.5390, 87.5836),
    "KHAGARIA": (25.5017, 86.4681), "KISHANGANJ": (26.0952, 87.9450),
    "KODERMA": (24.4619, 85.5963), "LAKHISARAI": (25.1560, 86.0940),
    "LOHARDAGA": (23.4352, 84.6862), "MADHEPURA": (25.9246, 86.7926),
    "MADHUBANI": (26.3569, 86.0716), "MUNGER": (25.3728, 86.4735),
    "MUZAFFARPUR": (26.1209, 85.3647), "NALANDA": (25.1100, 85.4400),
    "NAWADA": (24.8874, 85.5438), "PAKUR": (24.6349, 87.8448),
    "PALAMU": (24.0290, 84.0712), "PASHCHIM CHAMPARAN": (27.1595, 84.3908),
    "PATNA": (25.5941, 85.1376), "PURBI CHAMPARAN": (26.6393, 84.9165),
    "PURNIA": (25.7771, 87.4753), "RANCHI": (23.3441, 85.3096),
    "ROHTAS": (24.9950, 83.7907), "SAHARSA": (25.8784, 86.5954),
    "SAHEBGANJ": (25.2447, 87.6353), "SAMASTIPUR": (25.8580, 85.7783),
    "SARAN": (25.9145, 84.7508), "SHEIKHPURA": (25.1400, 85.8400),
    "SHEOHAR": (26.5191, 85.2985), "SITAMARHI": (26.5912, 85.4897),
    "SIWAN": (26.2195, 84.3556), "SUPAUL": (26.1230, 86.6042),
    "VAISHALI": (25.6903, 85.2091), "WEST SINGHBHUM": (22.5737, 85.8136),
    # MAHARASHTRA
    "AHMEDNAGAR": (19.0952, 74.7496), "AKOLA": (20.7002, 77.0082),
    "AMRAVATI": (20.9374, 77.7796), "AURANGABAD": (19.8762, 75.3433),
    "BEED": (18.9891, 75.7601), "BHANDARA": (21.1666, 79.6490),
    "BULDHANA": (20.5292, 76.1842), "CHANDRAPUR": (19.9615, 79.2961),
    "DHULE": (20.9042, 74.7749), "GADCHIROLI": (20.1809, 80.0000),
    "GONDIA": (21.4600, 80.1960), "HINGOLI": (19.7177, 77.1497),
    "JALGAON": (21.0077, 75.5626), "JALNA": (19.8347, 75.8816),
    "KOLHAPUR": (16.7050, 74.2433), "LATUR": (18.4088, 76.5604),
    "MUMBAI": (19.0760, 72.8777), "MUMBAI SUBURBAN": (19.1000, 72.9000),
    "NAGPUR": (21.1458, 79.0882), "NANDED": (19.1383, 77.3210),
    "NANDURBAR": (21.3700, 74.2437), "NASHIK": (19.9975, 73.7898),
    "OSMANABAD": (18.1862, 76.0427), "PALGHAR": (19.6967, 72.7697),
    "PARBHANI": (19.2709, 76.7742), "PUNE": (18.5204, 73.8567),
    "RAIGAD": (18.5158, 73.1298), "RATNAGIRI": (16.9902, 73.3120),
    "SANGLI": (16.8524, 74.5815), "SATARA": (17.6805, 74.0183),
    "SINDHUDURG": (16.3490, 73.7086), "SOLAPUR": (17.6599, 75.9064),
    "THANE": (19.2183, 72.9781), "WARDHA": (20.7453, 78.6022),
    "WASHIM": (20.1046, 77.1333), "YAVATMAL": (20.3888, 78.1204),
}

# District → State mapping
DISTRICT_STATE = {}
STATE_DISTRICTS = {
    'Uttar Pradesh': [
        "AGRA","ALIGARH","ALLAHABAD","ALMORA","AMBEDKAR NAGAR","AMETHI","AMROHA",
        "AURAIYA","AZAMGARH","BAGESHWAR","BAGHPAT","BAHRAICH","BALLIA","BALRAMPUR",
        "BANDA","BARABANKI","BAREILLY","BASTI","BIJNOR","BUDAUN","BULANDSHAHR",
        "CHAMOLI","CHAMPAWAT","CHANDAULI","CHITRAKOOT","DEHRADUN","DEORIA","ETAH",
        "ETAWAH","FAIZABAD","FARRUKHABAD","FATEHPUR","FIROZABAD","GAUTAM BUDDHA NAGAR",
        "GHAZIABAD","GHAZIPUR","GONDA","GORAKHPUR","HAMIRPUR","HAPUR","HARDOI",
        "HARIDWAR","HATHRAS","JALAUN","JAUNPUR","JHANSI","KANNAUJ","KANPUR DEHAT",
        "KANPUR NAGAR","KASGANJ","KAUSHAMBI","KHERI","KUSHI NAGAR","LALITPUR",
        "LUCKNOW","MAHARAJGANJ","MAHOBA","MAINPURI","MATHURA","MAU","MEERUT",
        "MIRZAPUR","MORADABAD","MUZAFFARNAGAR","NAINITAL","PAURI GARHWAL","PILIBHIT",
        "PITHORAGARH","PRATAPGARH","RAE BARELI","RAMPUR","RUDRA PRAYAG","SAHARANPUR",
        "SAMBHAL","SANT KABEER NAGAR","SANT RAVIDAS NAGAR","SHAHJAHANPUR","SHAMLI",
        "SHRAVASTI","SIDDHARTH NAGAR","SITAPUR","SONBHADRA","SULTANPUR","TEHRI GARHWAL",
        "UDAM SINGH NAGAR","UNNAO","UTTAR KASHI","VARANASI"
    ],
    'Madhya Pradesh': [
        "AGAR MALWA","ALIRAJPUR","ANUPPUR","ASHOKNAGAR","BALAGHAT","BARWANI","BASTAR",
        "BETUL","BHIND","BHOPAL","BILASPUR","BURHANPUR","CHHATARPUR","CHHINDWARA",
        "DAMOH","DANTEWADA","DATIA","DEWAS","DHAMTARI","DHAR","DINDORI","DURG",
        "GUNA","GWALIOR","HARDA","HOSHANGABAD","INDORE","JABALPUR","JANJGIR-CHAMPA",
        "JASHPUR","JHABUA","KABIRDHAM","KANKER","KATNI","KHANDWA","KHARGONE",
        "KORBA","KOREA","MAHASAMUND","MANDLA","MANDSAUR","MORENA","NARSINGHPUR",
        "NEEMUCH","NIWARI","PANNA","RAIPUR","RAISEN","RAJGARH","RAJNANDGAON",
        "RATLAM","REWA","SAGAR","SATNA","SEHORE","SEONI","SHAHDOL","SHAJAPUR",
        "SHEOPUR","SHIVPURI","SIDHI","SINGRAULI","SURGUJA","TIKAMGARH","UJJAIN",
        "UMARIA","VIDISHA"
    ],
    'Karnataka': [
        "BAGALKOTE","BALLARI","BANGALORE RURAL","BELAGAVI","BENGALURU URBAN","BIDAR",
        "CHAMARAJANAGARA","CHIKKABALLAPURA","CHIKKAMAGALURU","CHITRADURGA",
        "DAKSHINA KANNADA","DAVANGERE","DHARWAD","GADAG","HASSAN","HAVERI",
        "KALABURAGI","KODAGU","KOLAR","KOPPAL","MANDYA","MYSURU","RAICHUR",
        "RAMANAGARA","SHIVAMOGGA","TUMAKURU","UDUPI","UTTARA KANNADA","VIJAYAPURA",
        "YADAGIRI"
    ],
    'Bihar': [
        "ARARIA","ARWAL","AURANGABAD","BANKA","BEGUSARAI","BHAGALPUR","BHOJPUR",
        "BOKARO","BUXAR","CHATRA","DARBHANGA","DEOGHAR","DHANBAD","DUMKA",
        "EAST SINGHBUM","GARHWA","GAYA","GIRIDIH","GODDA","GOPALGANJ","GUMLA",
        "HAZARIBAGH","JAMUI","JEHANABAD","KAIMUR (BHABUA)","KATIHAR","KHAGARIA",
        "KISHANGANJ","KODERMA","LAKHISARAI","LOHARDAGA","MADHEPURA","MADHUBANI",
        "MUNGER","MUZAFFARPUR","NALANDA","NAWADA","PAKUR","PALAMU",
        "PASHCHIM CHAMPARAN","PATNA","PURBI CHAMPARAN","PURNIA","RANCHI","ROHTAS",
        "SAHARSA","SAHEBGANJ","SAMASTIPUR","SARAN","SHEIKHPURA","SHEOHAR",
        "SITAMARHI","SIWAN","SUPAUL","VAISHALI","WEST SINGHBHUM"
    ],
    'Maharashtra': [
        "AHMEDNAGAR","AKOLA","AMRAVATI","AURANGABAD","BEED","BHANDARA","BULDHANA",
        "CHANDRAPUR","DHULE","GADCHIROLI","GONDIA","HINGOLI","JALGAON","JALNA",
        "KOLHAPUR","LATUR","MUMBAI","MUMBAI SUBURBAN","NAGPUR","NANDED","NANDURBAR",
        "NASHIK","OSMANABAD","PALGHAR","PARBHANI","PUNE","RAIGAD","RATNAGIRI",
        "SANGLI","SATARA","SINDHUDURG","SOLAPUR","THANE","WARDHA","WASHIM","YAVATMAL"
    ],
}

for state, districts in STATE_DISTRICTS.items():
    for d in districts:
        DISTRICT_STATE[d] = state

# ── SEASON SLICING ────────────────────────────────────────────────────────────
def get_season_ndvi(monthly_ndvi: dict, season: str, crop_year: int) -> float:
    """
    Given a dict of {month_int: ndvi_float} for a calendar year,
    slice by season and return the mean NDVI.
    Crop_year = harvest year (same as APY Crop_Year).
    """
    if season in ('Kharif',):
        # Jun-Nov of crop_year
        months = [(crop_year, m) for m in range(6, 12)]
    elif season in ('Rabi',):
        # Oct-Dec of (crop_year-1) + Jan-Mar of crop_year
        months = [(crop_year - 1, m) for m in range(10, 13)] + \
                 [(crop_year, m) for m in range(1, 4)]
    elif season in ('Whole Year',):
        months = [(crop_year, m) for m in range(1, 13)]
    elif season in ('Summer',):
        months = [(crop_year, m) for m in range(3, 7)]
    else:
        months = [(crop_year, m) for m in range(1, 13)]

    vals = [monthly_ndvi.get((y, m)) for y, m in months
            if monthly_ndvi.get((y, m)) is not None]
    return float(np.mean(vals)) if vals else np.nan


# ── CORE GEE FETCH ────────────────────────────────────────────────────────────
def fetch_ndvi_for_year(year: int, districts: list) -> dict:
    """
    Fetches MODIS monthly NDVI for all districts in ONE GEE call per month.
    Returns: {district: {(year, month): ndvi_value}}

    Strategy:
    - Build a FeatureCollection of all district centroids
    - For each month, sample the MODIS image at all points simultaneously
    - Parse results into a nested dict
    """
    results = {d: {} for d in districts}

    # Build GEE FeatureCollection of all district centroids
    features = []
    for district in districts:
        lat, lon = DISTRICT_COORDS[district]
        feat = ee.Feature(
            ee.Geometry.Point([lon, lat]),
            {'district': district}
        )
        features.append(feat)
    fc = ee.FeatureCollection(features)

    # Fetch each month (12 calls per year, but each call covers all 276 districts)
    for month in range(1, 13):
        start = f"{year}-{month:02d}-01"
        # End: first day of next month
        if month == 12:
            end = f"{year + 1}-01-01"
        else:
            end = f"{year}-{month + 1:02d}-01"

        try:
            # Get MODIS image for this month
            collection = (ee.ImageCollection(MODIS_COLLECTION)
                          .filterDate(start, end)
                          .select(NDVI_BAND))

            # If no image available (e.g. pre-2000), skip
            count = collection.size().getInfo()
            if count == 0:
                continue

            image = collection.mean()

            # Sample all district points in one call
            sampled = image.reduceRegions(
                collection=fc,
                reducer=ee.Reducer.mean(),
                scale=1000  # MODIS 1km resolution
            )

            features_result = sampled.getInfo()['features']

            for feat in features_result:
                district = feat['properties']['district']
                raw_val = feat['properties'].get('mean')
                if raw_val is not None:
                    ndvi = raw_val * NDVI_SCALE_FACTOR
                    # MODIS valid NDVI range: -0.2 to 1.0 after scaling
                    if -0.2 <= ndvi <= 1.0:
                        results[district][(year, month)] = ndvi

        except Exception as e:
            print(f"    ⚠ Year {year} Month {month}: {e}")
            time.sleep(2)
            continue

        time.sleep(0.3)  # small pause between month calls

    return results


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────
def fetch_state(state_name: str, apy_df: pd.DataFrame):
    """Fetch NDVI for all districts in one state and save to CSV."""

    out_file = NDVI_RAW / f"ndvi_historical_{state_name.replace(' ', '_')}.csv"

    # Load cache if exists (resume support)
    done_years = set()
    cached_rows = []
    if os.path.exists(out_file):
        cache = pd.read_csv(out_file)
        done_years = set(cache['year'].unique())
        cached_rows = cache.to_dict('records')
        print(f"  Resuming {state_name}: {len(done_years)} years already done")

    districts = STATE_DISTRICTS[state_name]
    state_df = apy_df[apy_df['State'] == state_name]

    # Only years where MODIS data exists
    apy_years = sorted(state_df['Crop_Year'].unique())
    fetch_years = [y for y in apy_years if y >= MODIS_START_YEAR and y not in done_years]

    print(f"\n  {state_name}: {len(districts)} districts, {len(fetch_years)} years to fetch")

    new_rows = []

    for year in fetch_years:
        t0 = time.time()
        print(f"    Fetching year {year}...", end=' ', flush=True)

        monthly_data = fetch_ndvi_for_year(year, districts)
        elapsed = time.time() - t0
        print(f"done in {elapsed:.1f}s")

        # For each district, compute seasonal NDVI
        for district in districts:
            monthly = monthly_data[district]
            # Get unique (crop, season) combos for this district-year
            sub = state_df[(state_df['District'] == district) &
                           (state_df['Crop_Year'] == year)]

            for _, row in sub[['Crop', 'Season']].drop_duplicates().iterrows():
                season_ndvi = get_season_ndvi(monthly, row['Season'], year)
                new_rows.append({
                    'State': state_name,
                    'District': district,
                    'Crop': row['Crop'],
                    'Season': row['Season'],
                    'year': year,
                    'ndvi_season_mean': round(season_ndvi, 4) if not np.isnan(season_ndvi) else None,
                    'ndvi_months_available': len(monthly),
                })

        # Save after every year (crash safety)
        all_rows = cached_rows + new_rows
        pd.DataFrame(all_rows).to_csv(out_file, index=False)

    print(f"  ✅ {state_name} complete → {out_file}")
    return out_file


def merge_all_states():
    """Merge all per-state CSVs into one all-India file."""
    frames = []
    for state in TARGET_STATES:
        fname = NDVI_RAW / f"ndvi_historical_{state.replace(' ', '_')}.csv"
        if os.path.exists(fname):
            df = pd.read_csv(fname)
            frames.append(df)
            print(f"  Loaded {fname}: {len(df)} rows")
        else:
            print(f"  ⚠ Missing: {fname}")

    if frames:
        merged = pd.concat(frames, ignore_index=True)
        merged.to_csv(NDVI_RAW / "ndvi_historical_all.csv", index=False)
        print(f"\n✅ Merged file: ndvi_historical_all.csv ({len(merged)} rows)")
        print(f"   States: {merged['State'].nunique()}")
        print(f"   Districts: {merged['District'].nunique()}")
        print(f"   Year range: {merged['year'].min()} - {merged['year'].max()}")
        print(f"   NDVI null rate: {merged['ndvi_season_mean'].isna().mean()*100:.1f}%")
    else:
        print("No state files found to merge.")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=str, default=None,
                        help='Fetch one state only (e.g. "Uttar Pradesh")')
    parser.add_argument('--merge', action='store_true',
                        help='Merge all existing state files into ndvi_historical_all.csv')
    args = parser.parse_args()

    if args.merge:
        print("Merging state files...")
        merge_all_states()
        return

    # Initialize GEE
    print("Initializing Google Earth Engine...")
    ee.Initialize(project=GEE_PROJECT)
    print("✅ GEE initialized\n")

    # Load APY
    apy = pd.read_csv(RAW_DATA / 'APY.csv')
    apy.columns = apy.columns.str.strip()
    apy['District'] = apy['District'].str.strip()
    apy['State'] = apy['State'].str.strip()
    apy['Season'] = apy['Season'].str.strip()

    top16 = ['Rice','Maize','Moong(Green Gram)','Urad','Groundnut','Wheat',
             'Rapeseed &Mustard','Sugarcane','Arhar/Tur','Potato','Onion',
             'Gram','Jowar','Dry chillies','Bajra','Soyabean']
    apy = apy[apy['Crop'].isin(top16) & apy['State'].isin(TARGET_STATES)].copy()

    states_to_fetch = [args.state] if args.state else TARGET_STATES

    t_total = time.time()
    for state in states_to_fetch:
        if state not in TARGET_STATES:
            print(f"Unknown state: {state}. Choose from {TARGET_STATES}")
            continue
        fetch_state(state, apy)

    print(f"\n{'='*50}")
    print(f"Total time: {(time.time()-t_total)/60:.1f} minutes")
    print(f"\nNext steps:")
    print(f"  1. Run for each state separately if needed")
    print(f"  2. python fetch_ndvi_historical.py --merge")
    print(f"  3. Run fetch_weather_nasa.py to get historical weather+soil")
    print(f"  4. Run merge_and_train.py to build final dataset and train model")


if __name__ == '__main__':
    main()
