"""
fetch_ndvi_batch2.py
=====================
Fetches historical MODIS NDVI for 309 districts across 12 states:
Odisha, Rajasthan, Gujarat, Andhra Pradesh, Tamil Nadu, Assam,
Chhattisgarh, West Bengal, Haryana, Jharkhand, Punjab, Telangana

Same optimized approach as batch 1:
- 1 GEE call per month covers ALL districts in that state simultaneously
- Total calls: ~12 months × 20 years × 12 states = manageable
- Resume support: crashes don't lose progress
- Each state saves to its own CSV

Usage:
    # Fetch one state
    python fetch_ndvi_batch2.py --state "Rajasthan"

    # Fetch all batch 2 states
    python fetch_ndvi_batch2.py

    # Merge batch 2 states into one file
    python fetch_ndvi_batch2.py --merge-batch2

    # Merge batch 1 CSV + batch 2 CSV into final all-India file
    python fetch_ndvi_batch2.py --merge-all

Output:
    ndvi_historical_<State>.csv       per-state files
    ndvi_historical_batch2.csv        all batch 2 states merged
    ndvi_historical_all_india.csv     batch 1 + batch 2 combined
"""

from farm_yield.paths import RAW_DATA, NDVI_RAW, PROCESSED_DATA

import ee
import pandas as pd
import numpy as np
import os
import time
import argparse

# ── CONFIG ────────────────────────────────────────────────────────────────────
GEE_PROJECT      = 'madd-1eddf'
MODIS_COLLECTION = 'MODIS/061/MOD13A3'
NDVI_BAND        = 'NDVI'
NDVI_SCALE       = 0.0001
MODIS_START_YEAR = 2000
APY_END_YEAR     = 2019

BATCH2_STATES = [
    'Odisha', 'Rajasthan', 'Gujarat', 'Andhra Pradesh', 'Tamil Nadu',
    'Assam', 'Chhattisgarh', 'West Bengal', 'Haryana', 'Jharkhand',
    'Punjab', 'Telangana'
]

TOP16_CROPS = [
    'Rice', 'Maize', 'Moong(Green Gram)', 'Urad', 'Groundnut', 'Wheat',
    'Rapeseed &Mustard', 'Sugarcane', 'Arhar/Tur', 'Potato', 'Onion',
    'Gram', 'Jowar', 'Dry chillies', 'Bajra', 'Soyabean'
]

# ── DISTRICT COORDINATES ─────────────────────────────────────────────────────
DISTRICT_COORDS = {
    # ODISHA
    "ANUGUL":        (20.8400, 85.1000), "BALANGIR":      (20.7100, 83.4900),
    "BALESHWAR":     (21.4900, 86.9400), "BARGARH":       (21.3300, 83.6200),
    "BHADRAK":       (21.0600, 86.5100), "BOUDH":         (20.8400, 84.3300),
    "CUTTACK":       (20.4625, 85.8830), "DEOGARH":       (21.5300, 84.7300),
    "DHENKANAL":     (20.6600, 85.5900), "GAJAPATI":      (19.0700, 84.0800),
    "GANJAM":        (19.3900, 84.9800), "JAGATSINGHPUR": (20.2600, 86.1700),
    "JAJPUR":        (20.8500, 86.3300), "JHARSUGUDA":    (21.8500, 84.0100),
    "KALAHANDI":     (19.9100, 83.1600), "KANDHAMAL":     (20.1200, 84.2300),
    "KENDRAPARA":    (20.4900, 86.4200), "KENDUJHAR":     (21.6200, 85.5800),
    "KHORDHA":       (20.1800, 85.6200), "KORAPUT":       (18.8100, 82.7100),
    "MALKANGIRI":    (18.3500, 81.9000), "MAYURBHANJ":    (21.9400, 86.7300),
    "NABARANGPUR":   (19.2300, 82.5500), "NAYAGARH":      (20.1300, 85.0900),
    "NUAPADA":       (20.7800, 82.5400), "PURI":          (19.8100, 85.8300),
    "RAYAGADA":      (19.1700, 83.4200), "SAMBALPUR":     (21.4700, 83.9700),
    "SONEPUR":       (20.8300, 83.9100), "SUNDARGARH":    (22.1200, 84.0300),
    # RAJASTHAN
    "AJMER":         (26.4499, 74.6399), "ALWAR":         (27.5530, 76.6346),
    "BANSWARA":      (23.5500, 74.4400), "BARAN":         (25.1000, 76.5100),
    "BARMER":        (25.7500, 71.3900), "BHARATPUR":     (27.2152, 77.5030),
    "BHILWARA":      (25.3500, 74.6300), "BIKANER":       (28.0229, 73.3119),
    "BUNDI":         (25.4400, 75.6400), "CHITTORGARH":   (24.8800, 74.6300),
    "CHURU":         (28.3000, 74.9700), "DAUSA":         (26.8900, 76.3300),
    "DHOLPUR":       (26.7000, 77.9000), "DUNGARPUR":     (23.8400, 73.7100),
    "GANGANAGAR":    (29.9200, 73.8800), "HANUMANGARH":   (29.5800, 74.3300),
    "JAIPUR":        (26.9124, 75.7873), "JAISALMER":     (26.9157, 70.9083),
    "JALOR":         (25.3400, 72.6100), "JHALAWAR":      (24.5900, 76.1600),
    "JHUNJHUNU":     (28.1300, 75.4000), "JODHPUR":       (26.2389, 73.0243),
    "KARAULI":       (26.5000, 77.0200), "KOTA":          (25.2138, 75.8648),
    "NAGAUR":        (27.2000, 73.7300), "PALI":          (25.7700, 73.3300),
    "PRATAPGARH":    (24.0300, 74.7800), "RAJSAMAND":     (25.0700, 73.8800),
    "SAWAI MADHOPUR":(26.0000, 76.3600), "SIKAR":         (27.6100, 75.1400),
    "SIROHI":        (24.8900, 72.8600), "TONK":          (26.1700, 75.7900),
    "UDAIPUR":       (24.5854, 73.7125),
    # GUJARAT
    "AHMADABAD":     (23.0225, 72.5714), "AMRELI":        (21.6000, 71.2200),
    "ANAND":         (22.5645, 72.9289), "ARAVALLI":      (23.7000, 73.0000),
    "BANAS KANTHA":  (24.1700, 72.4300), "BHARUCH":       (21.7051, 72.9959),
    "BHAVNAGAR":     (21.7645, 72.1519), "BOTAD":         (22.1700, 71.6700),
    "CHHOTAUDEPUR":  (22.3000, 74.0100), "DANG":          (20.7600, 73.7000),
    "DEVBHUMI DWARKA":(22.3500,69.0100), "DOHAD":         (22.8400, 74.2600),
    "GANDHINAGAR":   (23.2156, 72.6369), "GIR SOMNATH":   (20.9000, 70.3600),
    "JAMNAGAR":      (22.4707, 70.0577), "JUNAGADH":      (21.5222, 70.4579),
    "KACHCHH":       (23.7337, 69.8597), "KHEDA":         (22.7500, 72.6800),
    "MAHESANA":      (23.5900, 72.3700), "MAHISAGAR":     (23.1000, 73.4500),
    "MORBI":         (22.8200, 70.8300), "NARMADA":       (21.8700, 73.7900),
    "NAVSARI":       (20.9500, 72.9200), "PANCH MAHALS":  (22.7600, 73.5900),
    "PATAN":         (23.8500, 72.1300), "PORBANDAR":     (21.6417, 69.6293),
    "RAJKOT":        (22.3039, 70.8022), "SABAR KANTHA":  (23.6400, 73.0000),
    "SURAT":         (21.1702, 72.8311), "SURENDRANAGAR": (22.7200, 71.6400),
    "TAPI":          (21.1200, 73.4100), "VADODARA":      (22.3072, 73.1812),
    "VALSAD":        (20.5992, 72.9342),
    # ANDHRA PRADESH
    "ADILABAD":      (19.6640, 78.5320), "ANANTAPUR":     (14.6819, 77.6006),
    "CHITTOOR":      (13.2172, 79.1003), "EAST GODAVARI": (17.0000, 81.8000),
    "GUNTUR":        (16.3067, 80.4365), "HYDERABAD":     (17.3850, 78.4867),
    "KADAPA":        (14.4674, 78.8241), "KARIMNAGAR":    (18.4386, 79.1288),
    "KHAMMAM":       (17.2473, 80.1514), "KRISHNA":       (16.6100, 80.7200),
    "KURNOOL":       (15.8281, 78.0373), "MAHBUBNAGAR":   (16.7488, 77.9864),
    "MEDAK":         (18.0500, 78.2600), "NALGONDA":      (17.0500, 79.2700),
    "NIZAMABAD":     (18.6725, 78.0941), "PRAKASAM":      (15.3300, 79.5700),
    "RANGAREDDI":    (17.3300, 78.1700), "SPSR NELLORE":  (14.4426, 79.9865),
    "SRIKAKULAM":    (18.2949, 83.8938), "VISAKHAPATNAM": (17.6868, 83.2185),
    "VIZIANAGARAM":  (18.1066, 83.3956), "WARANGAL":      (17.9784, 79.5941),
    "WEST GODAVARI": (16.9200, 81.3400),
    # TAMIL NADU
    "ARIYALUR":      (11.1400, 79.0800), "CHENGALPATTU":  (12.6921, 79.9764),
    "CHENNAI":       (13.0827, 80.2707), "COIMBATORE":    (11.0168, 76.9558),
    "CUDDALORE":     (11.7447, 79.7680), "DHARMAPURI":    (12.1279, 78.1580),
    "DINDIGUL":      (10.3624, 77.9695), "ERODE":         (11.3410, 77.7172),
    "KANCHIPURAM":   (12.8185, 79.6947), "KANNIYAKUMARI": (8.0883, 77.5385),
    "KARUR":         (10.9601, 78.0766), "KRISHNAGIRI":   (12.5186, 78.2137),
    "MADURAI":       (9.9252, 78.1198),  "NAGAPATTINAM":  (10.7672, 79.8420),
    "NAMAKKAL":      (11.2189, 78.1674), "PERAMBALUR":    (11.2338, 78.8800),
    "PUDUKKOTTAI":   (10.3797, 78.8200), "RAMANATHAPURAM":(9.3762, 78.8300),
    "SALEM":         (11.6643, 78.1460), "SIVAGANGA":     (9.8476, 78.4800),
    "THANJAVUR":     (10.7870, 79.1378), "THE NILGIRIS":  (11.4000, 76.7300),
    "THENI":         (10.0104, 77.4770), "THIRUVALLUR":   (13.1231, 79.9103),
    "THIRUVARUR":    (10.7667, 79.6333), "TIRUCHIRAPPALLI":(10.7905,78.7047),
    "TIRUNELVELI":   (8.7139, 77.7567),  "TIRUPATTUR":    (12.4950, 78.5726),
    "TIRUPPUR":      (11.1085, 77.3411), "TIRUVANNAMALAI":(12.2253, 79.0747),
    "TUTICORIN":     (8.7642, 78.1348),  "VELLORE":       (12.9165, 79.1325),
    "VILLUPURAM":    (11.9401, 79.4861), "VIRUDHUNAGAR":  (9.5851, 77.9624),
    # ASSAM
    "BAKSA":         (26.6700, 91.2000), "BARPETA":       (26.3200, 91.0000),
    "BONGAIGAON":    (26.4800, 90.5600), "CACHAR":        (24.8300, 92.7600),
    "CHIRANG":       (26.5000, 90.6300), "DARRANG":       (26.4400, 92.0000),
    "DHEMAJI":       (27.4800, 94.5600), "DHUBRI":        (26.0200, 89.9800),
    "DIBRUGARH":     (27.4800, 94.9100), "DIMA HASAO":    (25.5700, 93.0200),
    "GOALPARA":      (26.1700, 90.6200), "GOLAGHAT":      (26.5200, 93.9700),
    "HAILAKANDI":    (24.6800, 92.5600), "JORHAT":        (26.7500, 94.2200),
    "KAMRUP":        (26.3300, 91.7700), "KAMRUP METRO":  (26.1445, 91.7362),
    "KARBI ANGLONG": (26.0000, 93.5000), "KARIMGANJ":     (24.8700, 92.3600),
    "KOKRAJHAR":     (26.4000, 90.2700), "LAKHIMPUR":     (27.2300, 94.1000),
    "MARIGAON":      (26.3400, 92.3300), "NAGAON":        (26.3500, 92.6800),
    "NALBARI":       (26.4400, 91.4400), "SIVASAGAR":     (26.9800, 94.7900),
    "SONITPUR":      (26.6300, 92.8000), "TINSUKIA":      (27.4900, 95.3600),
    "UDALGURI":      (26.7500, 92.1000),
    # CHHATTISGARH
    "BALOD":         (20.7300, 81.2100), "BALODA BAZAR":  (21.6600, 82.1600),
    "BALRAMPUR":     (23.1000, 83.6000), "BASTAR":        (19.1174, 81.9538),
    "BEMETARA":      (21.7200, 81.5300), "BIJAPUR":       (18.8400, 80.2500),
    "BILASPUR":      (22.0797, 82.1391), "DANTEWADA":     (18.8956, 81.3473),
    "DHAMTARI":      (20.7060, 81.5482), "DURG":          (21.1900, 81.2849),
    "GARIYABAND":    (20.6400, 82.0800), "GAURELLA-PENDRA-MARWAHI":(22.7800,81.7400),
    "JANJGIR-CHAMPA":(22.0108, 82.5687),"JASHPUR":       (22.8862, 84.1356),
    "KABIRDHAM":     (22.0000, 81.2667), "KANKER":        (20.2739, 81.4921),
    "KONDAGAON":     (19.5900, 81.6700), "KORBA":         (22.3595, 82.7501),
    "KOREA":         (23.3091, 82.7265), "MAHASAMUND":    (21.1104, 82.0952),
    "MUNGELI":       (22.0700, 81.6800), "NARAYANPUR":    (19.6600, 81.2400),
    "RAIGARH":       (21.8974, 83.3950), "RAIPUR":        (21.2514, 81.6296),
    "RAJNANDGAON":   (21.0972, 81.0320), "SUKMA":         (18.3900, 81.6600),
    "SURAJPUR":      (23.2200, 82.8600), "SURGUJA":       (23.1165, 83.1940),
    # WEST BENGAL
    "ALIPURDUAR":    (26.4900, 89.5300), "BANKURA":       (23.2300, 87.0700),
    "BIRBHUM":       (23.9000, 87.5300), "COOCHBEHAR":    (26.3200, 89.4400),
    "DARJEELING":    (27.0360, 88.2627), "DINAJPUR DAKSHIN":(25.6200,88.6300),
    "DINAJPUR UTTAR":(25.3200, 88.6000),"HOOGHLY":       (22.9000, 88.3900),
    "HOWRAH":        (22.5958, 88.2636), "JALPAIGURI":    (26.5400, 88.7300),
    "JHARGRAM":      (22.4500, 86.9900), "KALIMPONG":     (27.0600, 88.4700),
    "MALDAH":        (25.0000, 88.1400), "MEDINIPUR EAST":(22.1700,87.7100),
    "MEDINIPUR WEST":(22.4300, 87.3200),"MURSHIDABAD":   (24.1800, 88.2700),
    "NADIA":         (23.4700, 88.5600), "PARAGANAS NORTH":(22.6900,88.4100),
    "PARAGANAS SOUTH":(22.1800,88.4600),"PASCHIM BARDHAMAN":(23.2300,87.0500),
    "PURBA BARDHAMAN":(23.2500,87.8500),"PURULIA":       (23.3300, 86.3600),
    # HARYANA
    "AMBALA":        (30.3752, 76.7821), "BHIWANI":       (28.7975, 76.1322),
    "CHARKI DADRI":  (28.5920, 76.2700), "FARIDABAD":     (28.4089, 77.3178),
    "FATEHABAD":     (29.5144, 75.4537), "GURGAON":       (28.4595, 77.0266),
    "HISAR":         (29.1492, 75.7217), "JHAJJAR":       (28.6082, 76.6570),
    "JIND":          (29.3163, 76.3123), "KAITHAL":       (29.8014, 76.3992),
    "KARNAL":        (29.6857, 76.9905), "KURUKSHETRA":   (29.9695, 76.8783),
    "MAHENDRAGARH":  (28.2729, 76.1459), "MEWAT":         (28.1027, 77.0198),
    "PALWAL":        (28.1488, 77.3312), "PANCHKULA":     (30.6942, 76.8606),
    "PANIPAT":       (29.3909, 76.9635), "REWARI":        (28.1911, 76.6183),
    "ROHTAK":        (28.8955, 76.6066), "SIRSA":         (29.5339, 75.0255),
    "SONIPAT":       (28.9288, 77.0218), "YAMUNANAGAR":   (30.1290, 77.2674),
    # JHARKHAND
    "BOKARO":        (23.6693, 85.9915), "CHATRA":        (24.2120, 84.8760),
    "DEOGHAR":       (24.4853, 86.6952), "DHANBAD":       (23.7957, 86.4304),
    "DUMKA":         (24.2663, 87.2476), "EAST SINGHBUM": (22.8046, 86.2029),
    "GARHWA":        (24.1695, 83.8118), "GIRIDIH":       (24.1851, 86.3009),
    "GODDA":         (24.8290, 87.2110), "GUMLA":         (23.0430, 84.5416),
    "HAZARIBAGH":    (23.9925, 85.3613), "JAMTARA":       (23.9600, 86.8000),
    "KHUNTI":        (23.0700, 85.2800), "KODERMA":       (24.4619, 85.5963),
    "LATEHAR":       (23.7400, 84.5000), "LOHARDAGA":     (23.4352, 84.6862),
    "PAKUR":         (24.6349, 87.8448), "PALAMU":        (24.0290, 84.0712),
    "RAMGARH":       (23.6300, 85.5100), "RANCHI":        (23.3441, 85.3096),
    "SAHEBGANJ":     (25.2447, 87.6353), "SARAIKELA KHARSAWAN":(22.7000,85.9400),
    "SIMDEGA":       (22.6100, 84.5100), "WEST SINGHBHUM":(22.5737, 85.8136),
    # PUNJAB
    "AMRITSAR":      (31.6340, 74.8723), "BARNALA":       (30.3800, 75.5500),
    "BATHINDA":      (30.2110, 74.9455), "FARIDKOT":      (30.6745, 74.7574),
    "FATEHGARH SAHIB":(30.6465,76.3911),"FAZILKA":       (30.4028, 74.0228),
    "FIROZPUR":      (30.9254, 74.6078), "GURDASPUR":     (32.0345, 75.4074),
    "HOSHIARPUR":    (31.5143, 75.9113), "JALANDHAR":     (31.3260, 75.5762),
    "KAPURTHALA":    (31.3806, 75.3823), "LUDHIANA":      (30.9010, 75.8573),
    "MANSA":         (29.9932, 75.3872), "MOGA":          (30.8168, 75.1699),
    "MUKTSAR":       (30.4722, 74.5174), "PATHANKOT":     (32.2643, 75.6522),
    "PATIALA":       (30.3398, 76.3869), "RUPNAGAR":      (30.9655, 76.5181),
    "S NAGAR":       (31.1215, 76.1156), "SANGRUR":       (30.2457, 75.8426),
    "SHAHID BHAGAT SINGH NAGAR":(31.1215,76.1156), "TARN TARAN":(31.4500,74.9300),
    # TELANGANA
    "ADILABAD":      (19.6640, 78.5320), "BHADRADRI":     (17.6000, 80.8900),
    "HANUMAKONDA":   (17.9784, 79.5941), "JAGTIAL":       (18.7900, 78.9100),
    "JANGOAN":       (17.7200, 79.1500), "JAYASHANKAR":   (18.3800, 79.9000),
    "JOGULAMBA":     (16.8300, 77.8000), "KAMAREDDY":     (18.3200, 78.3400),
    "KARIMNAGAR":    (18.4386, 79.1288), "KHAMMAM":       (17.2473, 80.1514),
    "KOMARAM BHEEM ASIFABAD":(19.3600,79.2900), "MAHABUBABAD":(17.6000,80.0000),
    "MAHBUBNAGAR":   (16.7488, 77.9864), "MANCHERIAL":    (18.8700, 79.4600),
    "MEDAK":         (18.0500, 78.2600), "MEDCHAL MALKAJGIRI":(17.5000,78.5500),
    "MULUGU":        (18.1900, 80.0500), "NAGARKURNOOL":  (16.4800, 78.3200),
    "NALGONDA":      (17.0500, 79.2700), "NARAYANPET":    (16.7400, 77.4900),
    "NIRMAL":        (19.0900, 78.3400), "NIZAMABAD":     (18.6725, 78.0941),
    "PEDDAPALLI":    (18.6100, 79.3800), "RAJANNA":       (18.4500, 78.8600),
    "RANGAREDDI":    (17.3300, 78.1700), "SANGAREDDY":    (17.6200, 78.0900),
    "SIDDIPET":      (18.1000, 78.8500), "SURYAPET":      (17.1400, 79.6200),
    "VIKARABAD":     (17.3300, 77.9000), "WANAPARTHY":    (16.3600, 78.0500),
    "WARANGAL":      (17.9784, 79.5941), "YADADRI":       (17.5700, 79.0300),
}

STATE_DISTRICTS = {
    'Odisha': ["ANUGUL","BALANGIR","BALESHWAR","BARGARH","BHADRAK","BOUDH","CUTTACK",
               "DEOGARH","DHENKANAL","GAJAPATI","GANJAM","JAGATSINGHPUR","JAJPUR",
               "JHARSUGUDA","KALAHANDI","KANDHAMAL","KENDRAPARA","KENDUJHAR","KHORDHA",
               "KORAPUT","MALKANGIRI","MAYURBHANJ","NABARANGPUR","NAYAGARH","NUAPADA",
               "PURI","RAYAGADA","SAMBALPUR","SONEPUR","SUNDARGARH"],
    'Rajasthan': ["AJMER","ALWAR","BANSWARA","BARAN","BARMER","BHARATPUR","BHILWARA",
                  "BIKANER","BUNDI","CHITTORGARH","CHURU","DAUSA","DHOLPUR","DUNGARPUR",
                  "GANGANAGAR","HANUMANGARH","JAIPUR","JAISALMER","JALOR","JHALAWAR",
                  "JHUNJHUNU","JODHPUR","KARAULI","KOTA","NAGAUR","PALI","PRATAPGARH",
                  "RAJSAMAND","SAWAI MADHOPUR","SIKAR","SIROHI","TONK","UDAIPUR"],
    'Gujarat': ["AHMADABAD","AMRELI","ANAND","ARAVALLI","BANAS KANTHA","BHARUCH",
                "BHAVNAGAR","BOTAD","CHHOTAUDEPUR","DANG","DEVBHUMI DWARKA","DOHAD",
                "GANDHINAGAR","GIR SOMNATH","JAMNAGAR","JUNAGADH","KACHCHH","KHEDA",
                "MAHESANA","MAHISAGAR","MORBI","NARMADA","NAVSARI","PANCH MAHALS",
                "PATAN","PORBANDAR","RAJKOT","SABAR KANTHA","SURAT","SURENDRANAGAR",
                "TAPI","VADODARA","VALSAD"],
    'Andhra Pradesh': ["ADILABAD","ANANTAPUR","CHITTOOR","EAST GODAVARI","GUNTUR",
                       "HYDERABAD","KADAPA","KARIMNAGAR","KHAMMAM","KRISHNA","KURNOOL",
                       "MAHBUBNAGAR","MEDAK","NALGONDA","NIZAMABAD","PRAKASAM",
                       "RANGAREDDI","SPSR NELLORE","SRIKAKULAM","VISAKHAPATNAM",
                       "VIZIANAGARAM","WARANGAL","WEST GODAVARI"],
    'Tamil Nadu': ["ARIYALUR","CHENGALPATTU","CHENNAI","COIMBATORE","CUDDALORE",
                   "DHARMAPURI","DINDIGUL","ERODE","KANCHIPURAM","KANNIYAKUMARI",
                   "KARUR","KRISHNAGIRI","MADURAI","NAGAPATTINAM","NAMAKKAL",
                   "PERAMBALUR","PUDUKKOTTAI","RAMANATHAPURAM","SALEM","SIVAGANGA",
                   "THANJAVUR","THE NILGIRIS","THENI","THIRUVALLUR","THIRUVARUR",
                   "TIRUCHIRAPPALLI","TIRUNELVELI","TIRUPATTUR","TIRUPPUR",
                   "TIRUVANNAMALAI","TUTICORIN","VELLORE","VILLUPURAM","VIRUDHUNAGAR"],
    'Assam': ["BAKSA","BARPETA","BONGAIGAON","CACHAR","CHIRANG","DARRANG","DHEMAJI",
              "DHUBRI","DIBRUGARH","DIMA HASAO","GOALPARA","GOLAGHAT","HAILAKANDI",
              "JORHAT","KAMRUP","KAMRUP METRO","KARBI ANGLONG","KARIMGANJ","KOKRAJHAR",
              "LAKHIMPUR","MARIGAON","NAGAON","NALBARI","SIVASAGAR","SONITPUR",
              "TINSUKIA","UDALGURI"],
    'Chhattisgarh': ["BALOD","BALODA BAZAR","BALRAMPUR","BASTAR","BEMETARA","BIJAPUR",
                     "BILASPUR","DANTEWADA","DHAMTARI","DURG","GARIYABAND",
                     "GAURELLA-PENDRA-MARWAHI","JANJGIR-CHAMPA","JASHPUR","KABIRDHAM",
                     "KANKER","KONDAGAON","KORBA","KOREA","MAHASAMUND","MUNGELI",
                     "NARAYANPUR","RAIGARH","RAIPUR","RAJNANDGAON","SUKMA","SURAJPUR",
                     "SURGUJA"],
    'West Bengal': ["ALIPURDUAR","BANKURA","BIRBHUM","COOCHBEHAR","DARJEELING",
                    "DINAJPUR DAKSHIN","DINAJPUR UTTAR","HOOGHLY","HOWRAH","JALPAIGURI",
                    "JHARGRAM","KALIMPONG","MALDAH","MEDINIPUR EAST","MEDINIPUR WEST",
                    "MURSHIDABAD","NADIA","PARAGANAS NORTH","PARAGANAS SOUTH",
                    "PASCHIM BARDHAMAN","PURBA BARDHAMAN","PURULIA"],
    'Haryana': ["AMBALA","BHIWANI","CHARKI DADRI","FARIDABAD","FATEHABAD","GURGAON",
                "HISAR","JHAJJAR","JIND","KAITHAL","KARNAL","KURUKSHETRA",
                "MAHENDRAGARH","MEWAT","PALWAL","PANCHKULA","PANIPAT","REWARI",
                "ROHTAK","SIRSA","SONIPAT","YAMUNANAGAR"],
    'Jharkhand': ["BOKARO","CHATRA","DEOGHAR","DHANBAD","DUMKA","EAST SINGHBUM",
                  "GARHWA","GIRIDIH","GODDA","GUMLA","HAZARIBAGH","JAMTARA","KHUNTI",
                  "KODERMA","LATEHAR","LOHARDAGA","PAKUR","PALAMU","RAMGARH","RANCHI",
                  "SAHEBGANJ","SARAIKELA KHARSAWAN","SIMDEGA","WEST SINGHBHUM"],
    'Punjab': ["AMRITSAR","BARNALA","BATHINDA","FARIDKOT","FATEHGARH SAHIB","FAZILKA",
               "FIROZPUR","GURDASPUR","HOSHIARPUR","JALANDHAR","KAPURTHALA","LUDHIANA",
               "MANSA","MOGA","MUKTSAR","PATHANKOT","PATIALA","RUPNAGAR","S NAGAR",
               "SANGRUR","SHAHID BHAGAT SINGH NAGAR","TARN TARAN"],
    'Telangana': ["ADILABAD","BHADRADRI","HANUMAKONDA","JAGTIAL","JANGOAN","JAYASHANKAR",
                  "JOGULAMBA","KAMAREDDY","KARIMNAGAR","KHAMMAM","KOMARAM BHEEM ASIFABAD",
                  "MAHABUBABAD","MAHBUBNAGAR","MANCHERIAL","MEDAK","MEDCHAL MALKAJGIRI",
                  "MULUGU","NAGARKURNOOL","NALGONDA","NARAYANPET","NIRMAL","NIZAMABAD",
                  "PEDDAPALLI","RAJANNA","RANGAREDDI","SANGAREDDY","SIDDIPET","SURYAPET",
                  "VIKARABAD","WANAPARTHY","WARANGAL","YADADRI"],
}


# ── SEASON SLICING ────────────────────────────────────────────────────────────
def get_season_ndvi(monthly_ndvi, season, crop_year):
    if season == 'Kharif':
        months = [(crop_year, m) for m in range(6, 12)]
    elif season == 'Rabi':
        months = [(crop_year-1, m) for m in range(10, 13)] + \
                 [(crop_year, m) for m in range(1, 4)]
    elif season == 'Whole Year':
        months = [(crop_year, m) for m in range(1, 13)]
    elif season == 'Summer':
        months = [(crop_year, m) for m in range(3, 7)]
    else:
        months = [(crop_year, m) for m in range(1, 13)]

    vals = [monthly_ndvi.get((y, m)) for y, m in months
            if monthly_ndvi.get((y, m)) is not None]
    return float(np.mean(vals)) if vals else np.nan


# ── GEE FETCH (same optimized batch logic as batch 1) ─────────────────────────
def fetch_ndvi_for_year(year, districts):
    results = {d: {} for d in districts}

    features = []
    for district in districts:
        if district not in DISTRICT_COORDS:
            continue
        lat, lon = DISTRICT_COORDS[district]
        features.append(ee.Feature(
            ee.Geometry.Point([lon, lat]),
            {'district': district}
        ))
    fc = ee.FeatureCollection(features)

    for month in range(1, 13):
        start = f"{year}-{month:02d}-01"
        end   = f"{year+1}-01-01" if month == 12 else f"{year}-{month+1:02d}-01"

        try:
            collection = (ee.ImageCollection(MODIS_COLLECTION)
                          .filterDate(start, end)
                          .select(NDVI_BAND))
            if collection.size().getInfo() == 0:
                continue

            image   = collection.mean()
            sampled = image.reduceRegions(
                collection=fc,
                reducer=ee.Reducer.mean(),
                scale=1000
            )

            for feat in sampled.getInfo()['features']:
                district = feat['properties']['district']
                raw      = feat['properties'].get('mean')
                if raw is not None:
                    ndvi = raw * NDVI_SCALE
                    if -0.2 <= ndvi <= 1.0:
                        results[district][(year, month)] = ndvi

        except Exception as e:
            print(f"    ⚠ {year}-{month:02d}: {e}")
            time.sleep(2)

        time.sleep(0.3)

    return results


# ── FETCH ONE STATE ───────────────────────────────────────────────────────────
def fetch_state(state_name, apy_df):
    out_file   = NDVI_RAW / f"ndvi_historical_{state_name.replace(' ', '_')}.csv"
    done_years = set()
    cached     = []

    if os.path.exists(out_file):
        cache      = pd.read_csv(out_file)
        done_years = set(cache['year'].unique())
        cached     = cache.to_dict('records')
        print(f"  Resuming {state_name}: {len(done_years)} years already done")

    districts = STATE_DISTRICTS[state_name]
    state_df  = apy_df[apy_df['State'] == state_name]
    apy_years = sorted(state_df['Crop_Year'].unique())
    fetch_years = [y for y in apy_years if y >= MODIS_START_YEAR and y not in done_years]

    print(f"\n  {state_name}: {len(districts)} districts, {len(fetch_years)} years to fetch")

    new_rows = []
    for year in fetch_years:
        t0 = time.time()
        print(f"    Fetching {year}...", end=' ', flush=True)
        monthly_data = fetch_ndvi_for_year(year, districts)
        print(f"done in {time.time()-t0:.1f}s")

        for district in districts:
            monthly = monthly_data.get(district, {})
            sub = state_df[(state_df['District'] == district) &
                           (state_df['Crop_Year'] == year)]
            for _, row in sub[['Crop', 'Season']].drop_duplicates().iterrows():
                new_rows.append({
                    'State':             state_name,
                    'District':          district,
                    'Crop':              row['Crop'],
                    'Season':            row['Season'],
                    'year':              year,
                    'ndvi_season_mean':  round(get_season_ndvi(monthly, row['Season'], year), 4)
                                         if not np.isnan(get_season_ndvi(monthly, row['Season'], year))
                                         else None,
                    'ndvi_months_available': len(monthly),
                })

        all_rows = cached + new_rows
        pd.DataFrame(all_rows).to_csv(out_file, index=False)

    print(f"  ✅ {state_name} → {out_file}")
    return out_file


# ── MERGE FUNCTIONS ───────────────────────────────────────────────────────────
def merge_batch2():
    """Merge all batch 2 state files into ndvi_historical_batch2.csv"""
    frames = []
    for state in BATCH2_STATES:
        fname = NDVI_RAW / f"ndvi_historical_{state.replace(' ', '_')}.csv"
        if os.path.exists(fname):
            df = pd.read_csv(fname)
            frames.append(df)
            print(f"  Loaded {fname}: {len(df)} rows")
        else:
            print(f"  ⚠ Missing: {fname}")

    if frames:
        merged = pd.concat(frames, ignore_index=True)
        merged.to_csv(NDVI_RAW / "ndvi_historical_batch2.csv", index=False)
        print(f"\n✅ ndvi_historical_batch2.csv saved ({len(merged)} rows)")
    else:
        print("No batch 2 files found.")


def merge_all_india(batch1_file=NDVI_RAW / "ndvi_historical_top5.csv",
                    batch2_file=NDVI_RAW / "ndvi_historical_batch2.csv"):
    """
    Merge batch 1 CSV (from fetch_ndvi_historical.py --merge)
    with batch 2 CSV into final ndvi_historical_all_india.csv
    """
    frames = []
    for f in [batch1_file, batch2_file]:
        if os.path.exists(f):
            df = pd.read_csv(f)
            frames.append(df)
            print(f"  Loaded {f}: {len(df)} rows, {df['State'].nunique()} states")
        else:
            print(f"  ⚠ Missing: {f}")

    if len(frames) == 2:
        merged = pd.concat(frames, ignore_index=True)
        merged = merged.drop_duplicates(subset=['State','District','Crop','Season','year'])
        merged.to_csv(PROCESSED_DATA / "ndvi_historical_all_india.csv", index=False)
        print(f"\n✅ ndvi_historical_all_india.csv saved")
        print(f"   Total rows:   {len(merged)}")
        print(f"   States:       {merged['State'].nunique()}")
        print(f"   Districts:    {merged['District'].nunique()}")
        print(f"   Year range:   {merged['year'].min()} – {merged['year'].max()}")
        print(f"   NDVI null %:  {merged['ndvi_season_mean'].isna().mean()*100:.1f}%")
    else:
        print("Need both batch files present to merge.")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=str, default=None,
                        help=f'Fetch one state. Options: {BATCH2_STATES}')
    parser.add_argument('--merge-batch2', action='store_true',
                        help='Merge all batch 2 state CSVs into ndvi_historical_batch2.csv')
    parser.add_argument('--merge-all', action='store_true',
                        help='Merge batch1 + batch2 into ndvi_historical_all_india.csv')
    args = parser.parse_args()

    if args.merge_batch2:
        merge_batch2()
        return

    if args.merge_all:
        merge_all_india()
        return

    print("Initializing Google Earth Engine...")
    ee.Initialize(project=GEE_PROJECT)
    print("✅ GEE initialized\n")

    apy = pd.read_csv(RAW_DATA / 'APY.csv')
    apy.columns = apy.columns.str.strip()
    apy['District'] = apy['District'].str.strip()
    apy['State']    = apy['State'].str.strip()
    apy['Season']   = apy['Season'].str.strip()
    apy = apy[apy['Crop'].isin(TOP16_CROPS) & apy['State'].isin(BATCH2_STATES)].copy()

    states_to_fetch = [args.state] if args.state else BATCH2_STATES

    t0 = time.time()
    for state in states_to_fetch:
        if state not in BATCH2_STATES:
            print(f"Unknown state: {state}")
            continue
        fetch_state(state, apy)

    print(f"\nTotal time: {(time.time()-t0)/60:.1f} min")
    print("\nNext steps:")
    print("  python fetch_ndvi_batch2.py --merge-batch2")
    print("  python fetch_ndvi_batch2.py --merge-all")


if __name__ == '__main__':
    main()
