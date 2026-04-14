"""
fetch_nasa_power.py
====================
Fetches historical weather + soil data from NASA POWER API for ALL 762
districts across India, for years 1997-2019.

NASA POWER advantages over Open-Meteo archive:
  - Free, no API key, no quota limits
  - Covers 1984-present
  - Daily data: temperature, rainfall, humidity, wind, soil moisture
  - Can fetch a full date range in ONE call per district (not per year)

SPEED OPTIMIZATION:
  - Parallel requests using ThreadPoolExecutor (20 workers)
  - Each district = 1 HTTP call for the FULL date range (1997-2019)
  - Total: 762 API calls (not 762 × 23 years)
  - Estimated time: ~15-25 minutes for all India

Variables fetched (daily):
  T2M       - Mean temperature at 2m (°C)
  T2M_MAX   - Max temperature (°C)
  T2M_MIN   - Min temperature (°C)
  PRECTOTCORR - Precipitation corrected (mm/day)
  RH2M      - Relative humidity at 2m (%)
  WS2M      - Wind speed at 2m (m/s)
  ALLSKY_SFC_SW_DWN - Solar radiation (MJ/m²/day)
  GWETROOT  - Root zone soil wetness (0-1)
  GWETTOP   - Top soil wetness (0-1)

Output:
  nasa_power_raw/          folder with one CSV per district
  nasa_power_seasonal.csv  aggregated seasonal features, ready to merge

Usage:
  python fetch_nasa_power.py            # fetch all districts
  python fetch_nasa_power.py --workers 10   # worker threads; API calls are paced separately
  python fetch_nasa_power.py --request-concurrency 1   # safest if NASA rate-limits
  python fetch_nasa_power.py --aggregate   # skip fetch, just aggregate already-fetched data
"""

import requests
import pandas as pd
import numpy as np
import os
import time
import argparse
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
RAW_DIR        = "nasa_power_raw"
OUTPUT_FILE    = "nasa_power_seasonal.csv"
APY_PATH       = "APY.csv"
START_DATE     = "19970101"
END_DATE       = "20191231"
MAX_WORKERS    = 20       # parallel threads — NASA POWER handles this fine
REQUEST_TIMEOUT = 60      # seconds
MAX_REQUEST_CONCURRENCY = 2
MIN_REQUEST_INTERVAL = 1.0
MAX_RETRIES = 6
RETRY_BACKOFF_BASE = 2.0
MAX_RETRY_WAIT = 90.0

NASA_PARAMS = ",".join([
    "T2M", "T2M_MAX", "T2M_MIN",
    "PRECTOTCORR", "RH2M", "WS2M",
    "ALLSKY_SFC_SW_DWN",
    "GWETROOT", "GWETTOP"
])

TOP16_CROPS = [
    'Rice', 'Maize', 'Moong(Green Gram)', 'Urad', 'Groundnut', 'Wheat',
    'Rapeseed &Mustard', 'Sugarcane', 'Arhar/Tur', 'Potato', 'Onion',
    'Gram', 'Jowar', 'Dry chillies', 'Bajra', 'Soyabean'
]

REQUEST_SEMAPHORE = threading.BoundedSemaphore(MAX_REQUEST_CONCURRENCY)
REQUEST_PACING_LOCK = threading.Lock()
THREAD_LOCAL = threading.local()
LAST_REQUEST_TS = 0.0

# ── ALL-INDIA DISTRICT COORDINATES ───────────────────────────────────────────
# Batch 1 + Batch 2 + remaining states
DISTRICT_COORDS = {
    # UTTAR PRADESH
    "AGRA":(27.1767,78.0081),"ALIGARH":(27.8974,78.0880),"ALLAHABAD":(25.4358,81.8463),
    "ALMORA":(29.5971,79.6591),"AMBEDKAR NAGAR":(26.3990,82.5437),"AMETHI":(26.1620,81.7370),
    "AMROHA":(28.9042,78.4678),"AURAIYA":(26.4605,79.5175),"AZAMGARH":(26.0672,83.1844),
    "BAGESHWAR":(29.8370,79.7714),"BAGHPAT":(28.9433,77.2166),"BAHRAICH":(27.5747,81.5964),
    "BALLIA":(25.7557,84.1465),"BALRAMPUR":(27.4312,82.1834),"BANDA":(25.4800,80.3330),
    "BARABANKI":(26.9342,81.1855),"BAREILLY":(28.3670,79.4304),"BASTI":(26.7946,82.7180),
    "BIJNOR":(29.3721,78.1358),"BUDAUN":(28.0408,79.1258),"BULANDSHAHR":(28.4069,77.8497),
    "CHAMOLI":(30.4021,79.3213),"CHAMPAWAT":(29.3350,80.0908),"CHANDAULI":(25.2596,83.2714),
    "CHITRAKOOT":(25.1906,80.8960),"DEHRADUN":(30.3165,78.0322),"DEORIA":(26.4979,83.7880),
    "ETAH":(27.5580,78.6717),"ETAWAH":(26.7853,79.0191),"FAIZABAD":(26.7751,82.1468),
    "FARRUKHABAD":(27.3874,79.5827),"FATEHPUR":(25.9300,80.8130),"FIROZABAD":(27.1592,78.3957),
    "GAUTAM BUDDHA NAGAR":(28.5355,77.3910),"GHAZIABAD":(28.6692,77.4538),
    "GHAZIPUR":(25.5796,83.5699),"GONDA":(27.1330,81.9604),"GORAKHPUR":(26.7606,83.3732),
    "HAMIRPUR":(25.9534,80.1537),"HAPUR":(28.7301,77.7757),"HARDOI":(27.3948,80.1379),
    "HARIDWAR":(29.9457,78.1642),"HATHRAS":(27.5958,78.0522),"JALAUN":(26.1413,79.3516),
    "JAUNPUR":(25.7463,82.6844),"JHANSI":(25.4484,78.5685),"KANNAUJ":(27.0553,79.9148),
    "KANPUR DEHAT":(26.4025,79.8208),"KANPUR NAGAR":(26.4499,80.3319),
    "KASGANJ":(27.8081,78.6447),"KAUSHAMBI":(25.5369,81.3890),"KHERI":(27.9506,80.7846),
    "KUSHI NAGAR":(26.7394,83.8870),"LALITPUR":(24.6882,78.4148),"LUCKNOW":(26.8467,80.9462),
    "MAHARAJGANJ":(27.1303,83.5608),"MAHOBA":(25.2891,79.8735),"MAINPURI":(27.2258,79.0078),
    "MATHURA":(27.4924,77.6737),"MAU":(25.9440,83.5615),"MEERUT":(28.9845,77.7064),
    "MIRZAPUR":(25.1448,82.5717),"MORADABAD":(28.8386,78.7733),"MUZAFFARNAGAR":(29.4727,77.7085),
    "NAINITAL":(29.3919,79.4542),"PAURI GARHWAL":(29.6956,78.9688),"PILIBHIT":(28.6317,79.8057),
    "PITHORAGARH":(29.5826,80.2180),"PRATAPGARH":(25.8996,81.9935),"RAE BARELI":(26.2328,81.2387),
    "RAMPUR":(28.8159,79.0256),"RUDRA PRAYAG":(30.2847,78.9808),"SAHARANPUR":(30.0289,77.1462),
    "SAMBHAL":(28.5904,78.5691),"SANT KABEER NAGAR":(26.7867,83.0566),
    "SANT RAVIDAS NAGAR":(25.3863,82.5672),"SHAHJAHANPUR":(27.8833,79.9053),
    "SHAMLI":(29.4490,77.3178),"SHRAVASTI":(27.5289,81.9335),"SIDDHARTH NAGAR":(27.2800,83.0681),
    "SITAPUR":(27.5632,80.6840),"SONBHADRA":(24.6826,83.0637),"SULTANPUR":(26.2613,82.0723),
    "TEHRI GARHWAL":(30.3817,78.4800),"UDAM SINGH NAGAR":(28.9995,79.5185),
    "UNNAO":(26.5455,80.4977),"UTTAR KASHI":(30.7268,78.4354),"VARANASI":(25.3176,82.9739),
    # MADHYA PRADESH
    "AGAR MALWA":(23.7121,76.0177),"ALIRAJPUR":(22.3085,74.3614),"ANUPPUR":(23.1031,81.6904),
    "ASHOKNAGAR":(24.5741,77.7285),"BALAGHAT":(21.8135,80.1862),"BARWANI":(22.0330,74.9021),
    "BASTAR":(19.1174,81.9538),"BETUL":(21.9074,77.9058),"BHIND":(26.5617,78.7870),
    "BHOPAL":(23.2599,77.4126),"BILASPUR":(22.0797,82.1391),"BURHANPUR":(21.3041,76.2279),
    "CHHATARPUR":(24.9176,79.5857),"CHHINDWARA":(22.0574,78.9382),"DAMOH":(23.8388,79.4419),
    "DANTEWADA":(18.8956,81.3473),"DATIA":(25.6677,78.4636),"DEWAS":(22.9623,76.0508),
    "DHAMTARI":(20.7060,81.5482),"DHAR":(22.5990,75.2999),"DINDORI":(22.9475,81.0791),
    "DURG":(21.1900,81.2849),"GUNA":(24.6479,77.3161),"GWALIOR":(26.2183,78.1828),
    "HARDA":(22.3393,77.0922),"HOSHANGABAD":(22.7479,77.7273),"INDORE":(22.7196,75.8577),
    "JABALPUR":(23.1815,79.9864),"JANJGIR-CHAMPA":(22.0108,82.5687),"JASHPUR":(22.8862,84.1356),
    "JHABUA":(22.7687,74.5931),"KABIRDHAM":(22.0000,81.2667),"KANKER":(20.2739,81.4921),
    "KATNI":(23.8333,80.4000),"KHANDWA":(21.8224,76.3508),"KHARGONE":(21.8230,75.6119),
    "KORBA":(22.3595,82.7501),"KOREA":(23.3091,82.7265),"MAHASAMUND":(21.1104,82.0952),
    "MANDLA":(22.5984,80.3730),"MANDSAUR":(24.0740,75.0688),"MORENA":(26.4944,77.9982),
    "NARSINGHPUR":(22.9496,79.1944),"NEEMUCH":(24.4765,74.8700),"NIWARI":(25.0000,79.0000),
    "PANNA":(24.7180,80.1856),"RAIPUR":(21.2514,81.6296),"RAISEN":(23.3265,77.7878),
    "RAJGARH":(23.9417,76.6920),"RAJNANDGAON":(21.0972,81.0320),"RATLAM":(23.3338,75.0376),
    "REWA":(24.5362,81.3037),"SAGAR":(23.8388,78.7378),"SATNA":(24.5869,80.8322),
    "SEHORE":(23.2017,77.0849),"SEONI":(22.0876,79.5373),"SHAHDOL":(23.2963,81.3511),
    "SHAJAPUR":(23.4273,76.2773),"SHEOPUR":(25.6584,76.7031),"SHIVPURI":(25.4258,77.6584),
    "SIDHI":(24.4160,81.8799),"SINGRAULI":(24.1997,82.6741),"SURGUJA":(23.1165,83.1940),
    "TIKAMGARH":(24.7431,78.8392),"UJJAIN":(23.1765,75.7885),"UMARIA":(23.5240,80.8378),
    "VIDISHA":(23.5252,77.8098),
    # KARNATAKA
    "BAGALKOTE":(16.1800,75.6960),"BALLARI":(15.1394,76.9214),"BANGALORE RURAL":(13.2257,77.5724),
    "BELAGAVI":(15.8497,74.4977),"BENGALURU URBAN":(12.9716,77.5946),"BIDAR":(17.9104,77.5199),
    "CHAMARAJANAGARA":(11.9265,76.9437),"CHIKKABALLAPURA":(13.4355,77.7315),
    "CHIKKAMAGALURU":(13.3161,75.7720),"CHITRADURGA":(14.2251,76.3980),
    "DAKSHINA KANNADA":(12.8438,75.2479),"DAVANGERE":(14.4644,75.9218),
    "DHARWAD":(15.4589,75.0078),"GADAG":(15.4317,75.6355),"HASSAN":(13.0072,76.1004),
    "HAVERI":(14.7957,75.3996),"KALABURAGI":(17.3297,76.8343),"KODAGU":(12.4200,75.7382),
    "KOLAR":(13.1367,78.1298),"KOPPAL":(15.3528,76.1547),"MANDYA":(12.5218,76.8951),
    "MYSURU":(12.2958,76.6394),"RAICHUR":(16.2120,77.3439),"RAMANAGARA":(12.7157,77.2799),
    "SHIVAMOGGA":(13.9299,75.5681),"TUMAKURU":(13.3392,77.1011),"UDUPI":(13.3409,74.7421),
    "UTTARA KANNADA":(14.7754,74.7551),"VIJAYAPURA":(16.8302,75.7100),"YADAGIRI":(16.7712,77.1370),
    # BIHAR
    "ARARIA":(26.1479,87.4710),"ARWAL":(25.2529,84.6812),"AURANGABAD":(24.7518,84.3741),
    "BANKA":(24.8800,86.9200),"BEGUSARAI":(25.4182,86.1272),"BHAGALPUR":(25.2425,86.9842),
    "BHOJPUR":(25.5599,84.5154),"BOKARO":(23.6693,85.9915),"BUXAR":(25.5655,83.9737),
    "CHATRA":(24.2120,84.8760),"DARBHANGA":(26.1542,85.8918),"DEOGHAR":(24.4853,86.6952),
    "DHANBAD":(23.7957,86.4304),"DUMKA":(24.2663,87.2476),"EAST SINGHBUM":(22.8046,86.2029),
    "GARHWA":(24.1695,83.8118),"GAYA":(24.7955,85.0002),"GIRIDIH":(24.1851,86.3009),
    "GODDA":(24.8290,87.2110),"GOPALGANJ":(26.4668,84.4374),"GUMLA":(23.0430,84.5416),
    "HAZARIBAGH":(23.9925,85.3613),"JAMUI":(24.9270,86.2240),"JEHANABAD":(25.2061,84.9879),
    "KAIMUR (BHABUA)":(25.0437,83.5988),"KATIHAR":(25.5390,87.5836),"KHAGARIA":(25.5017,86.4681),
    "KISHANGANJ":(26.0952,87.9450),"KODERMA":(24.4619,85.5963),"LAKHISARAI":(25.1560,86.0940),
    "LOHARDAGA":(23.4352,84.6862),"MADHEPURA":(25.9246,86.7926),"MADHUBANI":(26.3569,86.0716),
    "MUNGER":(25.3728,86.4735),"MUZAFFARPUR":(26.1209,85.3647),"NALANDA":(25.1100,85.4400),
    "NAWADA":(24.8874,85.5438),"PAKUR":(24.6349,87.8448),"PALAMU":(24.0290,84.0712),
    "PASHCHIM CHAMPARAN":(27.1595,84.3908),"PATNA":(25.5941,85.1376),
    "PURBI CHAMPARAN":(26.6393,84.9165),"PURNIA":(25.7771,87.4753),"RANCHI":(23.3441,85.3096),
    "ROHTAS":(24.9950,83.7907),"SAHARSA":(25.8784,86.5954),"SAHEBGANJ":(25.2447,87.6353),
    "SAMASTIPUR":(25.8580,85.7783),"SARAN":(25.9145,84.7508),"SHEIKHPURA":(25.1400,85.8400),
    "SHEOHAR":(26.5191,85.2985),"SITAMARHI":(26.5912,85.4897),"SIWAN":(26.2195,84.3556),
    "SUPAUL":(26.1230,86.6042),"VAISHALI":(25.6903,85.2091),"WEST SINGHBHUM":(22.5737,85.8136),
    # MAHARASHTRA
    "AHMEDNAGAR":(19.0952,74.7496),"AKOLA":(20.7002,77.0082),"AMRAVATI":(20.9374,77.7796),
    "BEED":(18.9891,75.7601),"BHANDARA":(21.1666,79.6490),"BULDHANA":(20.5292,76.1842),
    "CHANDRAPUR":(19.9615,79.2961),"DHULE":(20.9042,74.7749),"GADCHIROLI":(20.1809,80.0000),
    "GONDIA":(21.4600,80.1960),"HINGOLI":(19.7177,77.1497),"JALGAON":(21.0077,75.5626),
    "JALNA":(19.8347,75.8816),"KOLHAPUR":(16.7050,74.2433),"LATUR":(18.4088,76.5604),
    "MUMBAI":(19.0760,72.8777),"MUMBAI SUBURBAN":(19.1000,72.9000),"NAGPUR":(21.1458,79.0882),
    "NANDED":(19.1383,77.3210),"NANDURBAR":(21.3700,74.2437),"NASHIK":(19.9975,73.7898),
    "OSMANABAD":(18.1862,76.0427),"PALGHAR":(19.6967,72.7697),"PARBHANI":(19.2709,76.7742),
    "PUNE":(18.5204,73.8567),"RAIGAD":(18.5158,73.1298),"RATNAGIRI":(16.9902,73.3120),
    "SANGLI":(16.8524,74.5815),"SATARA":(17.6805,74.0183),"SINDHUDURG":(16.3490,73.7086),
    "SOLAPUR":(17.6599,75.9064),"THANE":(19.2183,72.9781),"WARDHA":(20.7453,78.6022),
    "WASHIM":(20.1046,77.1333),"YAVATMAL":(20.3888,78.1204),
    # ODISHA
    "ANUGUL":(20.8400,85.1000),"BALANGIR":(20.7100,83.4900),"BALESHWAR":(21.4900,86.9400),
    "BARGARH":(21.3300,83.6200),"BHADRAK":(21.0600,86.5100),"BOUDH":(20.8400,84.3300),
    "CUTTACK":(20.4625,85.8830),"DEOGARH":(21.5300,84.7300),"DHENKANAL":(20.6600,85.5900),
    "GAJAPATI":(19.0700,84.0800),"GANJAM":(19.3900,84.9800),"JAGATSINGHPUR":(20.2600,86.1700),
    "JAJPUR":(20.8500,86.3300),"JHARSUGUDA":(21.8500,84.0100),"KALAHANDI":(19.9100,83.1600),
    "KANDHAMAL":(20.1200,84.2300),"KENDRAPARA":(20.4900,86.4200),"KENDUJHAR":(21.6200,85.5800),
    "KHORDHA":(20.1800,85.6200),"KORAPUT":(18.8100,82.7100),"MALKANGIRI":(18.3500,81.9000),
    "MAYURBHANJ":(21.9400,86.7300),"NABARANGPUR":(19.2300,82.5500),"NAYAGARH":(20.1300,85.0900),
    "NUAPADA":(20.7800,82.5400),"PURI":(19.8100,85.8300),"RAYAGADA":(19.1700,83.4200),
    "SAMBALPUR":(21.4700,83.9700),"SONEPUR":(20.8300,83.9100),"SUNDARGARH":(22.1200,84.0300),
    # RAJASTHAN
    "AJMER":(26.4499,74.6399),"ALWAR":(27.5530,76.6346),"BANSWARA":(23.5500,74.4400),
    "BARAN":(25.1000,76.5100),"BARMER":(25.7500,71.3900),"BHARATPUR":(27.2152,77.5030),
    "BHILWARA":(25.3500,74.6300),"BIKANER":(28.0229,73.3119),"BUNDI":(25.4400,75.6400),
    "CHITTORGARH":(24.8800,74.6300),"CHURU":(28.3000,74.9700),"DAUSA":(26.8900,76.3300),
    "DHOLPUR":(26.7000,77.9000),"DUNGARPUR":(23.8400,73.7100),"GANGANAGAR":(29.9200,73.8800),
    "HANUMANGARH":(29.5800,74.3300),"JAIPUR":(26.9124,75.7873),"JAISALMER":(26.9157,70.9083),
    "JALOR":(25.3400,72.6100),"JHALAWAR":(24.5900,76.1600),"JHUNJHUNU":(28.1300,75.4000),
    "JODHPUR":(26.2389,73.0243),"KARAULI":(26.5000,77.0200),"KOTA":(25.2138,75.8648),
    "NAGAUR":(27.2000,73.7300),"PALI":(25.7700,73.3300),"RAJSAMAND":(25.0700,73.8800),
    "SAWAI MADHOPUR":(26.0000,76.3600),"SIKAR":(27.6100,75.1400),"SIROHI":(24.8900,72.8600),
    "TONK":(26.1700,75.7900),"UDAIPUR":(24.5854,73.7125),
    # GUJARAT
    "AHMADABAD":(23.0225,72.5714),"AMRELI":(21.6000,71.2200),"ANAND":(22.5645,72.9289),
    "ARAVALLI":(23.7000,73.0000),"BANAS KANTHA":(24.1700,72.4300),"BHARUCH":(21.7051,72.9959),
    "BHAVNAGAR":(21.7645,72.1519),"BOTAD":(22.1700,71.6700),"CHHOTAUDEPUR":(22.3000,74.0100),
    "DANG":(20.7600,73.7000),"DEVBHUMI DWARKA":(22.3500,69.0100),"DOHAD":(22.8400,74.2600),
    "GANDHINAGAR":(23.2156,72.6369),"GIR SOMNATH":(20.9000,70.3600),"JAMNAGAR":(22.4707,70.0577),
    "JUNAGADH":(21.5222,70.4579),"KACHCHH":(23.7337,69.8597),"KHEDA":(22.7500,72.6800),
    "MAHESANA":(23.5900,72.3700),"MAHISAGAR":(23.1000,73.4500),"MORBI":(22.8200,70.8300),
    "NARMADA":(21.8700,73.7900),"NAVSARI":(20.9500,72.9200),"PANCH MAHALS":(22.7600,73.5900),
    "PATAN":(23.8500,72.1300),"PORBANDAR":(21.6417,69.6293),"RAJKOT":(22.3039,70.8022),
    "SABAR KANTHA":(23.6400,73.0000),"SURAT":(21.1702,72.8311),"SURENDRANAGAR":(22.7200,71.6400),
    "TAPI":(21.1200,73.4100),"VADODARA":(22.3072,73.1812),"VALSAD":(20.5992,72.9342),
    # ANDHRA PRADESH
    "ADILABAD":(19.6640,78.5320),"ANANTAPUR":(14.6819,77.6006),"CHITTOOR":(13.2172,79.1003),
    "EAST GODAVARI":(17.0000,81.8000),"GUNTUR":(16.3067,80.4365),"HYDERABAD":(17.3850,78.4867),
    "KADAPA":(14.4674,78.8241),"KARIMNAGAR":(18.4386,79.1288),"KHAMMAM":(17.2473,80.1514),
    "KRISHNA":(16.6100,80.7200),"KURNOOL":(15.8281,78.0373),"MAHBUBNAGAR":(16.7488,77.9864),
    "MEDAK":(18.0500,78.2600),"NALGONDA":(17.0500,79.2700),"NIZAMABAD":(18.6725,78.0941),
    "PRAKASAM":(15.3300,79.5700),"RANGAREDDI":(17.3300,78.1700),"SPSR NELLORE":(14.4426,79.9865),
    "SRIKAKULAM":(18.2949,83.8938),"VISAKHAPATNAM":(17.6868,83.2185),"VIZIANAGARAM":(18.1066,83.3956),
    "WARANGAL":(17.9784,79.5941),"WEST GODAVARI":(16.9200,81.3400),
    # TAMIL NADU
    "ARIYALUR":(11.1400,79.0800),"CHENGALPATTU":(12.6921,79.9764),"CHENNAI":(13.0827,80.2707),
    "COIMBATORE":(11.0168,76.9558),"CUDDALORE":(11.7447,79.7680),"DHARMAPURI":(12.1279,78.1580),
    "DINDIGUL":(10.3624,77.9695),"ERODE":(11.3410,77.7172),"KANCHIPURAM":(12.8185,79.6947),
    "KANNIYAKUMARI":(8.0883,77.5385),"KARUR":(10.9601,78.0766),"KRISHNAGIRI":(12.5186,78.2137),
    "MADURAI":(9.9252,78.1198),"NAGAPATTINAM":(10.7672,79.8420),"NAMAKKAL":(11.2189,78.1674),
    "PERAMBALUR":(11.2338,78.8800),"PUDUKKOTTAI":(10.3797,78.8200),"RAMANATHAPURAM":(9.3762,78.8300),
    "SALEM":(11.6643,78.1460),"SIVAGANGA":(9.8476,78.4800),"THANJAVUR":(10.7870,79.1378),
    "THE NILGIRIS":(11.4000,76.7300),"THENI":(10.0104,77.4770),"THIRUVALLUR":(13.1231,79.9103),
    "THIRUVARUR":(10.7667,79.6333),"TIRUCHIRAPPALLI":(10.7905,78.7047),"TIRUNELVELI":(8.7139,77.7567),
    "TIRUPATTUR":(12.4950,78.5726),"TIRUPPUR":(11.1085,77.3411),"TIRUVANNAMALAI":(12.2253,79.0747),
    "TUTICORIN":(8.7642,78.1348),"VELLORE":(12.9165,79.1325),"VILLUPURAM":(11.9401,79.4861),
    "VIRUDHUNAGAR":(9.5851,77.9624),
    # ASSAM
    "BAKSA":(26.6700,91.2000),"BARPETA":(26.3200,91.0000),"BONGAIGAON":(26.4800,90.5600),
    "CACHAR":(24.8300,92.7600),"CHIRANG":(26.5000,90.6300),"DARRANG":(26.4400,92.0000),
    "DHEMAJI":(27.4800,94.5600),"DHUBRI":(26.0200,89.9800),"DIBRUGARH":(27.4800,94.9100),
    "DIMA HASAO":(25.5700,93.0200),"GOALPARA":(26.1700,90.6200),"GOLAGHAT":(26.5200,93.9700),
    "HAILAKANDI":(24.6800,92.5600),"JORHAT":(26.7500,94.2200),"KAMRUP":(26.3300,91.7700),
    "KAMRUP METRO":(26.1445,91.7362),"KARBI ANGLONG":(26.0000,93.5000),"KARIMGANJ":(24.8700,92.3600),
    "KOKRAJHAR":(26.4000,90.2700),"LAKHIMPUR":(27.2300,94.1000),"MARIGAON":(26.3400,92.3300),
    "NAGAON":(26.3500,92.6800),"NALBARI":(26.4400,91.4400),"SIVASAGAR":(26.9800,94.7900),
    "SONITPUR":(26.6300,92.8000),"TINSUKIA":(27.4900,95.3600),"UDALGURI":(26.7500,92.1000),
    # CHHATTISGARH
    "BALOD":(20.7300,81.2100),"BALODA BAZAR":(21.6600,82.1600),"BALRAMPUR":(23.1000,83.6000),
    "BEMETARA":(21.7200,81.5300),"BIJAPUR":(18.8400,80.2500),"KONDAGAON":(19.5900,81.6700),
    "MUNGELI":(22.0700,81.6800),"NARAYANPUR":(19.6600,81.2400),"RAIGARH":(21.8974,83.9350),
    "SUKMA":(18.3900,81.6600),"SURAJPUR":(23.2200,82.8600),
    "GAURELLA-PENDRA-MARWAHI":(22.7800,81.7400),
    # WEST BENGAL
    "ALIPURDUAR":(26.4900,89.5300),"BANKURA":(23.2300,87.0700),"BIRBHUM":(23.9000,87.5300),
    "COOCHBEHAR":(26.3200,89.4400),"DARJEELING":(27.0360,88.2627),"DINAJPUR DAKSHIN":(25.6200,88.6300),
    "DINAJPUR UTTAR":(25.3200,88.6000),"HOOGHLY":(22.9000,88.3900),"HOWRAH":(22.5958,88.2636),
    "JALPAIGURI":(26.5400,88.7300),"JHARGRAM":(22.4500,86.9900),"KALIMPONG":(27.0600,88.4700),
    "MALDAH":(25.0000,88.1400),"MEDINIPUR EAST":(22.1700,87.7100),"MEDINIPUR WEST":(22.4300,87.3200),
    "MURSHIDABAD":(24.1800,88.2700),"NADIA":(23.4700,88.5600),"PARAGANAS NORTH":(22.6900,88.4100),
    "PARAGANAS SOUTH":(22.1800,88.4600),"PASCHIM BARDHAMAN":(23.2300,87.0500),
    "PURBA BARDHAMAN":(23.2500,87.8500),"PURULIA":(23.3300,86.3600),
    # HARYANA
    "AMBALA":(30.3752,76.7821),"BHIWANI":(28.7975,76.1322),"CHARKI DADRI":(28.5920,76.2700),
    "FARIDABAD":(28.4089,77.3178),"FATEHABAD":(29.5144,75.4537),"GURGAON":(28.4595,77.0266),
    "HISAR":(29.1492,75.7217),"JHAJJAR":(28.6082,76.6570),"JIND":(29.3163,76.3123),
    "KAITHAL":(29.8014,76.3992),"KARNAL":(29.6857,76.9905),"KURUKSHETRA":(29.9695,76.8783),
    "MAHENDRAGARH":(28.2729,76.1459),"MEWAT":(28.1027,77.0198),"PALWAL":(28.1488,77.3312),
    "PANCHKULA":(30.6942,76.8606),"PANIPAT":(29.3909,76.9635),"REWARI":(28.1911,76.6183),
    "ROHTAK":(28.8955,76.6066),"SIRSA":(29.5339,75.0255),"SONIPAT":(28.9288,77.0218),
    "YAMUNANAGAR":(30.1290,77.2674),
    # JHARKHAND
    "JAMTARA":(23.9600,86.8000),"KHUNTI":(23.0700,85.2800),"LATEHAR":(23.7400,84.5000),
    "RAMGARH":(23.6300,85.5100),"SARAIKELA KHARSAWAN":(22.7000,85.9400),"SIMDEGA":(22.6100,84.5100),
    # PUNJAB
    "AMRITSAR":(31.6340,74.8723),"BARNALA":(30.3800,75.5500),"BATHINDA":(30.2110,74.9455),
    "FARIDKOT":(30.6745,74.7574),"FATEHGARH SAHIB":(30.6465,76.3911),"FAZILKA":(30.4028,74.0228),
    "FIROZPUR":(30.9254,74.6078),"GURDASPUR":(32.0345,75.4074),"HOSHIARPUR":(31.5143,75.9113),
    "JALANDHAR":(31.3260,75.5762),"KAPURTHALA":(31.3806,75.3823),"LUDHIANA":(30.9010,75.8573),
    "MANSA":(29.9932,75.3872),"MOGA":(30.8168,75.1699),"MUKTSAR":(30.4722,74.5174),
    "PATHANKOT":(32.2643,75.6522),"PATIALA":(30.3398,76.3869),"RUPNAGAR":(30.9655,76.5181),
    "S NAGAR":(31.1215,76.1156),"SANGRUR":(30.2457,75.8426),
    "SHAHID BHAGAT SINGH NAGAR":(31.1215,76.1156),"TARN TARAN":(31.4500,74.9300),
    # TELANGANA
    "BHADRADRI":(17.6000,80.8900),"HANUMAKONDA":(17.9784,79.5941),"JAGTIAL":(18.7900,78.9100),
    "JANGOAN":(17.7200,79.1500),"JAYASHANKAR":(18.3800,79.9000),"JOGULAMBA":(16.8300,77.8000),
    "KAMAREDDY":(18.3200,78.3400),"KOMARAM BHEEM ASIFABAD":(19.3600,79.2900),
    "MAHABUBABAD":(17.6000,80.0000),"MANCHERIAL":(18.8700,79.4600),
    "MEDCHAL MALKAJGIRI":(17.5000,78.5500),"MULUGU":(18.1900,80.0500),
    "NAGARKURNOOL":(16.4800,78.3200),"NARAYANPET":(16.7400,77.4900),"NIRMAL":(19.0900,78.3400),
    "PEDDAPALLI":(18.6100,79.3800),"RAJANNA":(18.4500,78.8600),"SANGAREDDY":(17.6200,78.0900),
    "SIDDIPET":(18.1000,78.8500),"SURYAPET":(17.1400,79.6200),"VIKARABAD":(17.3300,77.9000),
    "WANAPARTHY":(16.3600,78.0500),"YADADRI":(17.5700,79.0300),
    # REMAINING STATES
    "SRINAGAR":(34.0837,74.7973),"JAMMU":(32.7266,74.8570),"ANANTNAG":(33.7300,75.1500),
    "BARAMULLA":(34.2000,74.3400),"KUPWARA":(34.5200,74.2600),"PULWAMA":(33.8800,74.8900),
    "RAJOURI":(33.3800,74.3100),"POONCH":(33.7700,74.0900),"UDHAMPUR":(32.9300,75.1400),
    "KATHUA":(32.3800,75.5200),"DODA":(33.1500,75.5500),"KULGAM":(33.6400,75.0200),
    "SHOPIAN":(33.7200,74.8300),"GANDERBAL":(34.2300,74.7700),"BANDIPORA":(34.4200,74.6500),
    "SAMBA":(32.5700,75.1200),"KISHTWAR":(33.3100,75.7600),"RAMBAN":(33.2400,75.2400),
    "REASI":(33.0800,74.8300),"BUDGAM":(33.9200,74.7200),"KARGIL":(34.5600,76.1300),
    "LEH":(34.1526,77.5771),
    "THIRUVANANTHAPURAM":(8.5241,76.9366),"KOLLAM":(8.8932,76.6141),"PATHANAMTHITTA":(9.2648,76.7870),
    "ALAPPUZHA":(9.4981,76.3388),"KOTTAYAM":(9.5916,76.5222),"IDUKKI":(9.9189,77.1025),
    "ERNAKULAM":(9.9816,76.2999),"THRISSUR":(10.5276,76.2144),"PALAKKAD":(10.7867,76.6548),
    "MALAPPURAM":(11.0510,76.0711),"KOZHIKODE":(11.2588,75.7804),"WAYANAD":(11.6854,76.1320),
    "KANNUR":(11.8745,75.3704),"KASARAGOD":(12.4996,74.9869),
    "SHIMLA":(31.1048,77.1734),"MANDI":(31.7089,76.9320),"KANGRA":(32.0998,76.2691),
    "SOLAN":(30.9045,77.0967),"KULLU":(31.9579,77.1095),"HAMIRPUR HP":(31.6862,76.5215),
    "CHAMBA":(32.5534,76.1258),"UNA":(31.4685,76.2710),"BILASPUR HP":(31.3300,76.7600),
    "SIRMAUR":(30.5600,77.4600),"KINNAUR":(31.5900,78.4700),"LAHAUL AND SPITI":(32.5700,77.5600),
    "ITANAGAR":(27.0844,93.6053),"TAWANG":(27.5859,91.8681),"WEST KAMENG":(27.0500,92.3400),
    "EAST KAMENG":(27.2300,93.0200),"PAPUM PARE":(27.1000,93.7000),"KURUNG KUMEY":(27.8500,93.3300),
    "KRA DAADI":(27.9700,93.5200),"UPPER SUBANSIRI":(28.0800,94.2200),"WEST SIANG":(28.1500,94.6000),
    "EAST SIANG":(28.1000,95.2700),"SIANG":(28.0500,95.0000),"UPPER SIANG":(28.6000,95.3000),
    "DIBANG VALLEY":(28.7200,96.0000),"LOWER DIBANG VALLEY":(28.1000,95.8000),
    "LOHIT":(28.0000,96.2000),"NAMSAI":(27.6700,95.8300),"CHANGLANG":(27.1300,96.2700),
    "TIRAP":(26.9000,95.8400),"LONGDING":(26.7200,95.5800),"ANJAW":(28.0500,96.5000),
    "LEPA RADA":(28.1700,94.3000),"PAKKE KESSANG":(27.2000,93.4000),"SHI YOMI":(28.8000,94.0000),
    "KAMLE":(27.6900,93.8500),"BICHOM":(27.3000,92.2000),
    "IMPHAL WEST":(24.8170,93.9368),"IMPHAL EAST":(24.8170,93.9368),"THOUBAL":(24.6300,94.0100),
    "BISHNUPUR":(24.6200,93.7700),"SENAPATI":(25.2700,94.0200),"TAMENGLONG":(24.9800,93.5100),
    "CHURACHANDPUR":(24.3300,93.6800),"CHANDEL":(24.3300,94.0200),"UKHRUL":(25.1200,94.3600),
    "JIRIBAM":(24.7900,93.1200),
    "SHILLONG":(25.5788,91.8933),"EAST KHASI HILLS":(25.5700,91.8800),"WEST KHASI HILLS":(25.3200,91.1500),
    "RI BHOI":(25.8300,91.9300),"EAST JAINTIA HILLS":(25.3800,92.4600),"WEST JAINTIA HILLS":(25.3500,92.1900),
    "EAST GARO HILLS":(25.5100,90.8000),"WEST GARO HILLS":(25.5600,90.1800),"SOUTH GARO HILLS":(25.0200,90.4000),
    "NORTH GARO HILLS":(25.9000,90.5000),"EASTERN WEST KHASI HILLS":(25.2000,91.5000),
    "KOHIMA":(25.6701,94.1100),"DIMAPUR":(25.9071,93.7272),"MOKOKCHUNG":(26.3200,94.5200),
    "TUENSANG":(26.2700,94.8200),"MON":(26.7200,95.0500),"WOKHA":(26.1000,94.2600),
    "ZUNHEBOTO":(25.9900,94.5100),"PHEK":(25.6700,94.4700),"KIPHIRE":(25.9700,94.8200),
    "LONGLENG":(26.5600,94.5700),"PEREN":(25.5000,93.7300),"NOKLAK":(26.5200,95.1900),
    "AGARTALA":(23.8315,91.2868),"WEST TRIPURA":(23.7000,91.2700),"SOUTH TRIPURA":(23.2500,91.7700),
    "NORTH TRIPURA":(24.1200,92.2000),"KHOWAI":(24.0700,91.6000),"GOMATI":(23.4200,91.8500),
    "SEPAHIJALA":(23.5700,91.3800),"UNAKOTI":(24.2200,92.0200),
    "AIZAWL":(23.7271,92.7176),"LUNGLEI":(22.8800,92.7900),"CHAMPHAI":(23.4600,93.3200),
    "KOLASIB":(24.2300,92.6800),"SERCHHIP":(23.3000,92.8500),"LAWNGTLAI":(22.0200,92.9000),
    "MAMIT":(23.9200,92.4900),"SIAHA":(22.4700,92.9700),
    "GANGTOK":(27.3314,88.6138),"EAST SIKKIM":(27.3300,88.6100),"WEST SIKKIM":(27.2900,88.2500),
    "NORTH SIKKIM":(27.8800,88.5500),"SOUTH SIKKIM":(27.1500,88.4800),
    "PANAJI":(15.4909,73.8278),"NORTH GOA":(15.5000,73.9000),"SOUTH GOA":(15.1700,74.0000),
    "DELHI":(28.6139,77.2090),
    "PUDUCHERRY":(11.9416,79.8083),"KARAIKAL":(10.9254,79.8380),"MAHE":(11.7010,75.5414),
    "YANAM":(16.7333,82.2167),
    "SILVASSA":(20.2740,73.0169),"DADRA":(20.3500,73.0300),"NAGAR HAVELI":(20.2500,72.9600),
    "DIU":(20.7144,70.9874),"DAMAN":(20.4142,72.8326),
    "NICOBAR":(7.0000,93.7500),"NORTH MIDDLE ANDAMAN":(12.5000,92.8000),"SOUTH ANDAMAN":(11.6234,92.7265),
    "LEH LADAKH":(34.1526,77.5771),"KARGIL LADAKH":(34.5560,76.1349),
    "CHANDIGARH":(30.7333,76.7794),
}


# ── SEASON WINDOW ─────────────────────────────────────────────────────────────
def get_date_range(season, crop_year):
    """Return (start_yyyymmdd, end_yyyymmdd) for a given season and harvest year."""
    if season == 'Whole Year':
        return f"{crop_year}0101", f"{crop_year}1231"
    elif season == 'Rabi':
        return f"{crop_year-1}1001", f"{crop_year}0331"
    elif season == 'Kharif':
        return f"{crop_year}0601", f"{crop_year}1130"
    elif season == 'Summer':
        return f"{crop_year}0301", f"{crop_year}0630"
    else:
        return f"{crop_year}0101", f"{crop_year}1231"


# ── NASA POWER API CALL ───────────────────────────────────────────────────────
def configure_request_throttle(max_concurrent, min_interval):
    """Apply shared throttling across all worker threads."""
    global REQUEST_SEMAPHORE, LAST_REQUEST_TS, MIN_REQUEST_INTERVAL
    REQUEST_SEMAPHORE = threading.BoundedSemaphore(max(1, int(max_concurrent)))
    MIN_REQUEST_INTERVAL = max(0.0, float(min_interval))
    LAST_REQUEST_TS = 0.0


def get_thread_session():
    session = getattr(THREAD_LOCAL, 'session', None)
    if session is None:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Farm-Level-Yield-Estimation/1.0 (NASA POWER fetch)'
        })
        THREAD_LOCAL.session = session
    return session


def get_retry_delay(response, attempt):
    """Use Retry-After when present; otherwise exponential backoff with jitter."""
    retry_after = response.headers.get('Retry-After')
    if retry_after:
        try:
            return min(MAX_RETRY_WAIT, max(1.0, float(retry_after)))
        except ValueError:
            try:
                retry_dt = parsedate_to_datetime(retry_after)
                if retry_dt.tzinfo is None:
                    retry_dt = retry_dt.replace(tzinfo=timezone.utc)
                seconds = (retry_dt - datetime.now(timezone.utc)).total_seconds()
                return min(MAX_RETRY_WAIT, max(1.0, seconds))
            except (TypeError, ValueError, OverflowError):
                pass

    backoff = RETRY_BACKOFF_BASE * (2 ** max(0, attempt - 1))
    return min(MAX_RETRY_WAIT, backoff + random.uniform(0.0, 1.0))


def fetch_power_json(url):
    """Fetch JSON with shared pacing and retries for transient NASA POWER failures."""
    global LAST_REQUEST_TS
    session = get_thread_session()
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        retry_delay = None

        with REQUEST_SEMAPHORE:
            with REQUEST_PACING_LOCK:
                elapsed = time.monotonic() - LAST_REQUEST_TS
                wait_for = MIN_REQUEST_INTERVAL - elapsed
                if wait_for > 0:
                    time.sleep(wait_for)
                LAST_REQUEST_TS = time.monotonic()

            try:
                resp = session.get(url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                last_error = exc
                retry_delay = min(
                    MAX_RETRY_WAIT,
                    RETRY_BACKOFF_BASE * (2 ** max(0, attempt - 1)) + random.uniform(0.0, 1.0)
                )
            else:
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    last_error = requests.HTTPError(
                        f"{resp.status_code} {resp.reason}: {url}",
                        response=resp
                    )
                    retry_delay = get_retry_delay(resp, attempt)
                else:
                    resp.raise_for_status()
                    return resp.json(), None

        if retry_delay is None or attempt == MAX_RETRIES:
            break

        time.sleep(retry_delay)

    return None, str(last_error) if last_error else "Unknown NASA POWER request failure"


def fetch_district_weather(district, state, lat, lon, seasons_needed):
    """
    Fetches the FULL date range (1997-2019) in ONE API call per district.
    Then slices by season in pandas — no extra calls needed.

    seasons_needed: list of (season, crop_year) tuples for this district
    Returns: list of row dicts
    """
    raw_file = os.path.join(RAW_DIR, f"{district.replace(' ','_').replace('/','_')}.csv")

    # Load from cache if already fetched
    if os.path.exists(raw_file):
        try:
            daily = pd.read_csv(raw_file, parse_dates=['date'])
            daily = daily.set_index('date')
        except Exception:
            os.remove(raw_file)
            daily = None
    else:
        daily = None

    if daily is None:
        url = (
            f"https://power.larc.nasa.gov/api/temporal/daily/point"
            f"?parameters={NASA_PARAMS}"
            f"&community=AG"
            f"&longitude={lon}&latitude={lat}"
            f"&start={START_DATE}&end={END_DATE}"
            f"&format=JSON"
        )
        try:
            data, fetch_error = fetch_power_json(url)
            if fetch_error:
                return [], fetch_error

            params_data = data.get('properties', {}).get('parameter', {})
            dates = list(params_data.get('T2M', {}).keys())
            if not dates:
                return [], f"No NASA POWER daily data returned for {district}"

            rows = []
            for d in dates:
                row = {'date': pd.to_datetime(d, format='%Y%m%d')}
                for param in ['T2M','T2M_MAX','T2M_MIN','PRECTOTCORR',
                              'RH2M','WS2M','ALLSKY_SFC_SW_DWN','GWETROOT','GWETTOP']:
                    val = params_data.get(param, {}).get(d, -999)
                    row[param] = None if val == -999 else val
                rows.append(row)

            daily = pd.DataFrame(rows).set_index('date').sort_index()
            if daily.empty:
                return [], f"Empty NASA POWER dataset parsed for {district}"

            daily.to_csv(raw_file)

        except Exception as e:
            return [], str(e)

    # Slice by each (season, crop_year) and aggregate
    output_rows = []
    for season, crop_year in seasons_needed:
        start_str, end_str = get_date_range(season, crop_year)
        start_dt = pd.to_datetime(start_str, format='%Y%m%d')
        end_dt   = pd.to_datetime(end_str,   format='%Y%m%d')

        window = daily[(daily.index >= start_dt) & (daily.index <= end_dt)].copy()
        if len(window) < 10:
            continue

        output_rows.append({
            'State':              state,
            'District':           district,
            'Season':             season,
            'Crop_Year':          crop_year,
            'temp_mean_c':        window['T2M'].mean(),
            'temp_max_c':         window['T2M_MAX'].mean(),
            'temp_min_c':         window['T2M_MIN'].mean(),
            'rainfall_mm':        window['PRECTOTCORR'].sum(),
            'humidity_pct':       window['RH2M'].mean(),
            'wind_speed_ms':      window['WS2M'].mean(),
            'solar_radiation_mj': window['ALLSKY_SFC_SW_DWN'].sum(),
            'et0_mm':             np.nan,
            'soil_moisture_root': window['GWETROOT'].mean(),
            'soil_moisture_surface': window['GWETTOP'].mean(),
            'season_days':        len(window),
        })

    return output_rows, None


# ── MAIN PIPELINE ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=MAX_WORKERS)
    parser.add_argument('--request-concurrency', type=int, default=MAX_REQUEST_CONCURRENCY,
                        help='Max concurrent NASA POWER HTTP requests across all workers')
    parser.add_argument('--min-request-interval', type=float, default=MIN_REQUEST_INTERVAL,
                        help='Minimum seconds between request starts across all workers')
    parser.add_argument('--aggregate', action='store_true',
                        help='Skip fetch, just aggregate already-downloaded raw files')
    args = parser.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    configure_request_throttle(args.request_concurrency, args.min_request_interval)

    # Load APY
    apy = pd.read_csv(APY_PATH)
    apy.columns = apy.columns.str.strip()
    apy['District'] = apy['District'].str.strip()
    apy['State']    = apy['State'].str.strip()
    apy['Season']   = apy['Season'].str.strip()
    apy = apy[apy['Crop'].isin(TOP16_CROPS) & apy['Production'].notna()].copy()

    # Build job list: per district, what (season, year) combos do we need?
    district_jobs = {}
    for _, row in apy[['State','District','Season','Crop_Year']].drop_duplicates().iterrows():
        key = (row['District'], row['State'])
        if key not in district_jobs:
            district_jobs[key] = []
        district_jobs[key].append((row['Season'], row['Crop_Year']))

    # Filter to districts we have coords for
    valid_jobs = {k: v for k, v in district_jobs.items() if k[0] in DISTRICT_COORDS}
    missing    = set(d for d, s in district_jobs.keys()) - set(DISTRICT_COORDS.keys())

    print(f"Total districts in APY: {len(district_jobs)}")
    print(f"Districts with coords:  {len(valid_jobs)}")
    if missing:
        print(f"Missing coords ({len(missing)}): {sorted(missing)[:10]}...")

    errors = []

    # Check which already have raw files (skip re-fetching)
    if not args.aggregate:
        to_fetch = [(d, s, v) for (d, s), v in valid_jobs.items()
                    if not os.path.exists(
                        os.path.join(RAW_DIR, f"{d.replace(' ','_').replace('/','_')}.csv")
                    )]
        already  = len(valid_jobs) - len(to_fetch)
        print(f"\nAlready cached: {already} districts")
        print(f"To fetch:       {len(to_fetch)} districts")
        print(f"Workers:        {args.workers}")
        print(f"API concurrency:{args.request_concurrency}")
        print(f"Min interval:   {args.min_request_interval:.2f}s")
        print(f"Est. time:      {len(to_fetch) * 3 / args.workers / 60:.1f} – "
              f"{len(to_fetch) * 8 / args.workers / 60:.1f} minutes\n")

        done   = 0
        fetched = 0
        t0     = time.time()

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    fetch_district_weather,
                    district, state,
                    DISTRICT_COORDS[district][0],
                    DISTRICT_COORDS[district][1],
                    seasons
                ): district
                for district, state, seasons in to_fetch
            }

            for future in as_completed(futures):
                district = futures[future]
                done += 1
                try:
                    rows, err = future.result()
                    if err:
                        errors.append((district, err))
                    else:
                        fetched += 1
                    if done % 50 == 0 or done == len(to_fetch):
                        elapsed = time.time() - t0
                        rate    = done / elapsed
                        remaining = (len(to_fetch) - done) / rate / 60 if rate > 0 else 0
                        print(f"  [{done}/{len(to_fetch)}] {elapsed/60:.1f}min elapsed, "
                              f"~{remaining:.1f}min remaining")
                except Exception as e:
                    errors.append((district, str(e)))

        print(f"\nFetched raw data for: {fetched} districts")
        if errors:
            print(f"\n⚠ {len(errors)} errors:")
            for d, e in errors[:10]:
                print(f"  {d}: {e}")

    # Aggregate all raw CSVs into seasonal features
    print("\nAggregating seasonal features from raw files...")
    all_rows = []

    for (district, state), seasons in valid_jobs.items():
        raw_file = os.path.join(RAW_DIR, f"{district.replace(' ','_').replace('/','_')}.csv")
        if not os.path.exists(raw_file):
            continue
        try:
            daily = pd.read_csv(raw_file, parse_dates=['date']).set_index('date')
        except Exception:
            continue

        for season, crop_year in seasons:
            start_str, end_str = get_date_range(season, crop_year)
            start_dt = pd.to_datetime(start_str, format='%Y%m%d')
            end_dt   = pd.to_datetime(end_str,   format='%Y%m%d')
            window   = daily[(daily.index >= start_dt) & (daily.index <= end_dt)]

            if len(window) < 10:
                continue

            all_rows.append({
                'State':              state,
                'District':           district,
                'Season':             season,
                'Crop_Year':          crop_year,
                'temp_mean_c':        round(window['T2M'].mean(), 3),
                'temp_max_c':         round(window['T2M_MAX'].mean(), 3),
                'temp_min_c':         round(window['T2M_MIN'].mean(), 3),
                'rainfall_mm':        round(window['PRECTOTCORR'].sum(), 2),
                'humidity_pct':       round(window['RH2M'].mean(), 2),
                'wind_speed_ms':      round(window['WS2M'].mean(), 3),
                'solar_radiation_mj': round(window['ALLSKY_SFC_SW_DWN'].sum(), 2),
                'et0_mm':             np.nan,
                'soil_moisture_root': round(window['GWETROOT'].mean(), 4),
                'soil_moisture_surface': round(window['GWETTOP'].mean(), 4),
                'season_days':        len(window),
            })

    result = pd.DataFrame(all_rows)
    if result.empty:
        print("\nNo seasonal rows could be built from cached NASA POWER raw files.")
        if errors:
            print("Fetch step finished with errors before any usable raw district files were cached.")
        print(f"Skipped writing {OUTPUT_FILE} because there is no data yet.")
        print("\nTry rerunning with the defaults or lower API pressure further:")
        print("  python fetch_nasa_power.py --workers 4 --request-concurrency 1 --min-request-interval 1.5")
        return

    result.to_csv(OUTPUT_FILE, index=False)

    print(f"\n✅ Done! Saved: {OUTPUT_FILE}")
    print(f"   Rows:      {len(result)}")
    print(f"   Districts: {result['District'].nunique()}")
    print(f"   States:    {result['State'].nunique()}")
    print(f"   Years:     {result['Crop_Year'].min()} – {result['Crop_Year'].max()}")
    print(f"   Null %:    {result.isnull().mean().mean()*100:.1f}%")
    print(f"\nNext: run merge_and_train.py to combine with NDVI and APY yield data")


if __name__ == '__main__':
    main()
